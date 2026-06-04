let chart = null;
let currentCSV = null;
let lastResult = null;
let previewTimer = null;
let previewController = null;
let fitController = null;
let progressTimer = null;
let needsInitialGuess = false;

const defaultParams = { Jph: 10, J01: 1e-12, J02: 1e-8, n1: 1, n2: 2, Rs: 1, Rsh: 2000 };
const paramBounds = {
    Jph: { min: 0, max: 50, step: 0.01 },
    J01: { min: 1e-20, max: 1e-5, step: 0.05, log: true },
    J02: { min: 1e-15, max: 1e-3, step: 0.05, log: true },
    n1: { min: 0.5, max: 2, step: 0.001 },
    n2: { min: 1, max: 4, step: 0.001 },
    Rs: { min: 0.01, max: 100, step: 0.01 },
    Rsh: { min: 10, max: 1e6, step: 1 }
};
const paramLabels = { Jph: 'Jph / Jsc', J01: 'J01', J02: 'J02', n1: 'n1', n2: 'n2', Rs: 'Rs', Rsh: 'Rsh' };

function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
}

function formatValue(name, value) {
    if (!Number.isFinite(value)) return '--';
    if (paramBounds[name]?.log || Math.abs(value) >= 1e4 || (Math.abs(value) > 0 && Math.abs(value) < 1e-3)) {
        return value.toExponential(4);
    }
    return value.toFixed(name === 'Rsh' ? 2 : 4);
}

function valueToSlider(name, value) {
    return paramBounds[name].log ? Math.log10(Math.max(value, 1e-30)) : value;
}

function sliderToValue(name, value) {
    return paramBounds[name].log ? 10 ** value : value;
}

function setStatus(message, kind = 'idle') {
    const box = document.getElementById('statusBox');
    box.textContent = message;
    box.dataset.kind = kind;
}

function initParams() {
    const container = document.getElementById('paramContainer');
    for (const [name, value] of Object.entries(defaultParams)) {
        const bounds = paramBounds[name];
        const item = document.createElement('div');
        item.className = 'param-item';
        item.innerHTML = `
            <div class="param-header">
                <span class="param-name">${paramLabels[name]}</span>
                <label class="fixed-checkbox"><input type="checkbox" id="fixed-${name}"><span>锁定</span></label>
            </div>
            <div class="param-live-value" id="live-${name}">${formatValue(name, value)}</div>
            <input type="range" class="param-slider" id="slider-${name}">
            <div class="param-inputs">
                <label class="param-input"><span>Min</span><input type="number" id="min-${name}" value="${bounds.min}" step="any"></label>
                <label class="param-input"><span>Max</span><input type="number" id="max-${name}" value="${bounds.max}" step="any"></label>
                <label class="param-input"><span>Val</span><input type="number" id="val-${name}" value="${value}" step="any"></label>
            </div>`;
        container.appendChild(item);

        const slider = document.getElementById(`slider-${name}`);
        slider.min = bounds.log ? Math.log10(bounds.min) : bounds.min;
        slider.max = bounds.log ? Math.log10(bounds.max) : bounds.max;
        slider.step = bounds.step;
        slider.value = valueToSlider(name, value);
        slider.addEventListener('input', () => {
            setParamValue(name, sliderToValue(name, Number(slider.value)), false);
            schedulePreview();
        });
        document.getElementById(`val-${name}`).addEventListener('input', () => {
            syncSliderFromValue(name);
            schedulePreview();
        });
        document.getElementById(`min-${name}`).addEventListener('change', () => updateBoundsForParam(name));
        document.getElementById(`max-${name}`).addEventListener('change', () => updateBoundsForParam(name));
    }
}

function setParamValue(name, value, updateSlider = true) {
    const min = Number(document.getElementById(`min-${name}`).value);
    const max = Number(document.getElementById(`max-${name}`).value);
    const safeValue = clamp(value, min, max);
    document.getElementById(`val-${name}`).value = safeValue;
    document.getElementById(`live-${name}`).textContent = formatValue(name, safeValue);
    if (updateSlider) document.getElementById(`slider-${name}`).value = valueToSlider(name, safeValue);
}

function syncSliderFromValue(name) {
    const value = Number(document.getElementById(`val-${name}`).value);
    if (Number.isFinite(value)) setParamValue(name, value);
}

function updateBoundsForParam(name) {
    const slider = document.getElementById(`slider-${name}`);
    let min = Number(document.getElementById(`min-${name}`).value);
    let max = Number(document.getElementById(`max-${name}`).value);
    if (!Number.isFinite(min)) min = paramBounds[name].min;
    if (!Number.isFinite(max)) max = paramBounds[name].max;
    if (paramBounds[name].log) min = Math.max(min, 1e-30);
    document.getElementById(`min-${name}`).value = min;
    document.getElementById(`max-${name}`).value = max;
    slider.min = valueToSlider(name, min);
    slider.max = valueToSlider(name, Math.max(max, min));
    syncSliderFromValue(name);
    schedulePreview();
}

function getCurrentParams() {
    const params = {};
    const bounds = {};
    const fixed = {};
    for (const name of Object.keys(defaultParams)) {
        params[name] = Number(document.getElementById(`val-${name}`).value);
        bounds[name] = {
            min: Number(document.getElementById(`min-${name}`).value),
            max: Number(document.getElementById(`max-${name}`).value)
        };
        fixed[name] = document.getElementById(`fixed-${name}`).checked;
    }
    return { params, bounds, fixed };
}

async function parseApiResponse(response) {
    const data = await response.json().catch(() => null);
    if (!data) throw new Error(`服务器返回无法解析的响应 (${response.status})`);
    if (!response.ok || !data.success) throw new Error(data.error || `请求失败 (${response.status})`);
    return data;
}

function initChart() {
    chart = new Chart(document.getElementById('jvChart'), {
        type: 'scatter',
        data: { datasets: [
            { label: '实验数据', data: [], borderColor: '#2563eb', backgroundColor: '#2563eb', pointRadius: 4 },
            { label: '模型曲线', data: [], borderColor: '#dc2626', backgroundColor: '#dc2626', borderWidth: 2, pointRadius: 0, showLine: true }
        ]},
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: { title: { display: true, text: 'J-V Curve Analysis' }, legend: { position: 'top' } },
            scales: {
                x: { type: 'linear', title: { display: true, text: 'Voltage (V)' } },
                y: { type: 'linear', title: { display: true, text: 'Current Density (mA/cm²)' } }
            }
        }
    });
}

function updateChart(V, experimental, fitted = null) {
    chart.data.datasets[0].data = V.map((x, index) => ({ x, y: experimental[index] }));
    chart.data.datasets[1].data = fitted ? V.map((x, index) => ({ x, y: fitted[index] })) : [];
    chart.update('none');
}

function updateMetrics(data = null) {
    document.getElementById('metricRmse').textContent = data?.rmse != null ? data.rmse.toFixed(6) : '--';
    document.getElementById('metricJsc').textContent = data?.meta?.Jsc != null ? formatValue('Jph', data.meta.Jsc) : '--';
    document.getElementById('metricVoc').textContent = data?.meta?.Voc != null ? `${data.meta.Voc.toFixed(4)} V` : '--';
    document.getElementById('metricMode').textContent = data?.meta?.quality === 'good' ? '可靠' : data?.meta?.quality === 'warning' ? '需复核' : '--';
}

function updateQuality(meta = {}) {
    const box = document.getElementById('qualityBox');
    const warnings = meta.warnings || [];
    box.classList.toggle('hidden', !warnings.length);
    box.dataset.kind = warnings.length ? 'warning' : 'good';
    box.textContent = warnings.join('\n');
}

function setResultText(data, prefix = '') {
    const meta = data.meta || {};
    const selectionLabel = meta.selection_metric === 'balanced' ? '低电流优先' : '整体 RMSE';
    const lines = [
        `${prefix}RMSE: ${data.rmse.toFixed(6)}`,
        `模式: ${meta.mode || '--'}`,
        `入选候选: ${meta.selected_candidate || '--'}`,
        `择优标准: ${selectionLabel}`,
        `阶段: ${(meta.stages || []).join(' → ') || '--'}`,
        `求解收敛点: ${meta.solver?.converged_points ?? '--'} / ${meta.solver?.points ?? '--'}`,
        `优化评估次数: ${meta.optimizer?.evaluations ?? '--'}`,
        ''
    ];
    for (const [name, value] of Object.entries(data.params)) {
        lines.push(`${name}: ${formatValue(name, value)}${data.fixed?.[name] ? ' [锁定]' : ''}`);
    }
    if (meta.candidates?.length) {
        lines.push('', '候选对比:');
        for (const candidate of meta.candidates) {
            const selectedMark = candidate.name === meta.selected_candidate ? ' [入选]' : '';
            lines.push(
                `- ${candidate.name}${selectedMark}: RMSE=${candidate.rmse.toFixed(6)}, 综合评分=${candidate.balanced_score.toFixed(6)}`
            );
        }
    }
    if (meta.warnings?.length) lines.push('', '警告:', ...meta.warnings.map(item => `- ${item}`));
    document.getElementById('resultContainer').textContent = lines.join('\n');
    updateMetrics(data);
    updateQuality(meta);
}

function updateInputsFromParams(params) {
    for (const [name, value] of Object.entries(params)) setParamValue(name, value);
}

function parseAndPreviewUploadedCsv() {
    needsInitialGuess = true;
    setStatus('正在由后端校验并解析数据...', 'running');
    schedulePreview(0);
}

function schedulePreview(delay = 250) {
    window.clearTimeout(previewTimer);
    if (currentCSV && !fitController) previewTimer = window.setTimeout(runPreview, delay);
}

async function runPreview() {
    if (!currentCSV || fitController) return;
    previewController?.abort();
    previewController = new AbortController();
    const { params, bounds } = getCurrentParams();
    try {
        const response = await fetch('/api/preview', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ csv: currentCSV, params, bounds }), signal: previewController.signal
        });
        const data = await parseApiResponse(response);
        updateChart(data.V, data.J_exp, data.J_fit);
        setResultText(data, '[参数预览] ');
        if (needsInitialGuess && Number.isFinite(data.meta?.Jsc)) {
            needsInitialGuess = false;
            const jsc = data.meta.Jsc;
            document.getElementById('min-Jph').value = Math.max(jsc * 0.75, 1e-9);
            document.getElementById('max-Jph').value = Math.max(jsc * 1.25, jsc + 1e-6);
            updateBoundsForParam('Jph');
            setParamValue('Jph', jsc);
            schedulePreview(0);
        }
        setStatus(`已解析 ${data.V.length} 个数据点，参数预览已更新。`, 'ready');
    } catch (error) {
        if (error.name !== 'AbortError') setStatus(`预览失败：${error.message}`, 'error');
    } finally {
        previewController = null;
    }
}

function setFitRunning(running, options = {}) {
    const fitButton = document.getElementById('fitBtn');
    const cancelButton = document.getElementById('cancelFitBtn');
    document.getElementById('progress').classList.toggle('hidden', !running);
    document.getElementById('progressText').classList.toggle('hidden', !running);
    fitButton.disabled = running;
    fitButton.textContent = running ? '正式拟合中...' : '开始正式拟合';
    cancelButton.classList.toggle('hidden', !running);
    window.clearInterval(progressTimer);
    if (!running) return;
    const stages = ['线性最小二乘', ...(options.use_global ? ['差分进化'] : []), ...(options.use_nelder ? ['Nelder-Mead'] : []), ...(options.use_log ? ['低电流候选'] : []), '自动择优'];
    let progress = 8;
    let stageIndex = 0;
    document.getElementById('progressFill').style.width = `${progress}%`;
    document.getElementById('progressText').textContent = `正在执行：${stages[stageIndex]}`;
    progressTimer = window.setInterval(() => {
        progress = Math.min(progress + 3, 92);
        stageIndex = Math.min(Math.floor(progress / (100 / stages.length)), stages.length - 1);
        document.getElementById('progressFill').style.width = `${progress}%`;
        document.getElementById('progressText').textContent = `正在执行：${stages[stageIndex]}`;
    }, 900);
}

async function runFit() {
    if (!currentCSV) return setStatus('请先导入 CSV 或选择示例数据。', 'error');
    previewController?.abort();
    const { params, bounds, fixed } = getCurrentParams();
    const options = {
        use_global: document.getElementById('useGlobal').checked,
        use_nelder: document.getElementById('useNelder').checked,
        use_log: document.getElementById('useLog').checked,
        selection_metric: document.querySelector('input[name="selectionMetric"]:checked').value
    };
    fitController = new AbortController();
    setFitRunning(true, options);
    setStatus('正式拟合由 SciPy 后端执行，可随时取消等待。', 'running');
    try {
        const response = await fetch('/api/fit', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ csv: currentCSV, params, bounds, fixed, options }), signal: fitController.signal
        });
        const data = await parseApiResponse(response);
        lastResult = data;
        updateChart(data.V, data.J_exp, data.J_fit);
        setResultText(data);
        updateInputsFromParams(data.params);
        document.getElementById('exportParams').disabled = false;
        document.getElementById('exportCSV').disabled = false;
        setStatus(data.meta?.warnings?.length ? '拟合完成，但存在需要复核的诊断警告。' : '拟合完成，诊断未发现明显问题。', data.meta?.warnings?.length ? 'warning' : 'ready');
    } catch (error) {
        setStatus(error.name === 'AbortError' ? '已取消本次拟合等待。' : `拟合失败：${error.message}`, error.name === 'AbortError' ? 'idle' : 'error');
    } finally {
        fitController = null;
        setFitRunning(false);
    }
}

async function loadSample(sampleId) {
    try {
        setStatus('正在载入示例数据...', 'running');
        const data = await parseApiResponse(await fetch(`/api/sample/${sampleId}`));
        currentCSV = data.csv;
        document.getElementById('fileName').textContent = data.name;
        parseAndPreviewUploadedCsv();
    } catch (error) {
        setStatus(`示例数据载入失败：${error.message}`, 'error');
    }
}

function download(content, type, filename) {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
}

document.getElementById('csvFile').addEventListener('change', event => {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 1_500_000) return setStatus('CSV 文件超过 1.5 MB 限制。', 'error');
    document.getElementById('fileName').textContent = file.name;
    const reader = new FileReader();
    reader.onload = loadEvent => { currentCSV = loadEvent.target.result; parseAndPreviewUploadedCsv(); };
    reader.readAsText(file);
});
document.querySelectorAll('[data-sample]').forEach(button => button.addEventListener('click', () => loadSample(button.dataset.sample)));
document.getElementById('fitBtn').addEventListener('click', runFit);
document.getElementById('cancelFitBtn').addEventListener('click', () => fitController?.abort());
document.getElementById('exportParams').addEventListener('click', () => {
    if (lastResult) download(JSON.stringify(lastResult, null, 2), 'application/json;charset=utf-8', 'fit_diagnostics.json');
});
document.getElementById('exportCSV').addEventListener('click', () => {
    if (!lastResult) return;
    const rows = ['V,J_Exp,J_Fit', ...lastResult.V.map((value, index) => `${value},${lastResult.J_exp[index]},${lastResult.J_fit[index]}`)];
    download(rows.join('\n'), 'text/csv;charset=utf-8', 'fit_result.csv');
});

document.addEventListener('DOMContentLoaded', () => {
    initParams();
    initChart();
    updateMetrics();
});
