let chart = null;
let currentCSV = null;
let lastResult = null;
let previewTimer = null;
let previewController = null;

const defaultParams = {
    Jph: 10,
    J01: 1e-12,
    J02: 1e-8,
    n1: 1.0,
    n2: 2.0,
    Rs: 1.0,
    Rsh: 2000
};

const paramBounds = {
    Jph: { min: 0, max: 50, step: 0.01 },
    J01: { min: 1e-20, max: 1e-5, step: 0.05, log: true },
    J02: { min: 1e-15, max: 1e-3, step: 0.05, log: true },
    n1: { min: 0.5, max: 2.0, step: 0.001 },
    n2: { min: 1.0, max: 4.0, step: 0.001 },
    Rs: { min: 0.01, max: 100, step: 0.01 },
    Rsh: { min: 10, max: 1e6, step: 1 }
};

const paramLabels = {
    Jph: 'Jph / Jsc',
    J01: 'J01',
    J02: 'J02',
    n1: 'n1',
    n2: 'n2',
    Rs: 'Rs',
    Rsh: 'Rsh'
};

function formatValue(name, value) {
    if (!Number.isFinite(value)) return '';
    if (paramBounds[name].log || Math.abs(value) >= 1e4 || Math.abs(value) < 1e-3) {
        return value.toExponential(4);
    }
    return value.toFixed(name === 'Rsh' ? 2 : 4);
}

function valueToSlider(name, value) {
    return paramBounds[name].log ? Math.log10(Math.max(value, 1e-30)) : value;
}

function sliderToValue(name, value) {
    return paramBounds[name].log ? Math.pow(10, value) : value;
}

function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
}

function initParams() {
    const container = document.getElementById('paramContainer');
    container.innerHTML = '';

    for (const [name, val] of Object.entries(defaultParams)) {
        const bounds = paramBounds[name];
        const div = document.createElement('div');
        div.className = 'param-item';
        div.innerHTML = `
            <div class="param-header">
                <span class="param-name">${paramLabels[name]}</span>
                <label class="fixed-checkbox">
                    <input type="checkbox" id="fixed-${name}">
                    <span>锁定</span>
                </label>
            </div>
            <div class="param-live-value" id="live-${name}">${formatValue(name, val)}</div>
            <input type="range" class="param-slider" id="slider-${name}">
            <div class="param-inputs">
                <label class="param-input">
                    <span>Min</span>
                    <input type="number" id="min-${name}" value="${bounds.min}" step="any">
                </label>
                <label class="param-input">
                    <span>Max</span>
                    <input type="number" id="max-${name}" value="${bounds.max}" step="any">
                </label>
                <label class="param-input">
                    <span>Val</span>
                    <input type="number" id="val-${name}" value="${val}" step="any">
                </label>
            </div>
        `;
        container.appendChild(div);

        const slider = document.getElementById(`slider-${name}`);
        slider.min = bounds.log ? Math.log10(bounds.min) : bounds.min;
        slider.max = bounds.log ? Math.log10(bounds.max) : bounds.max;
        slider.step = bounds.step;
        slider.value = valueToSlider(name, val);

        slider.addEventListener('input', () => {
            const value = sliderToValue(name, parseFloat(slider.value));
            setParamValue(name, value, false);
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
    const min = parseFloat(document.getElementById(`min-${name}`).value);
    const max = parseFloat(document.getElementById(`max-${name}`).value);
    const safeValue = clamp(value, min, max);
    document.getElementById(`val-${name}`).value = safeValue;
    document.getElementById(`live-${name}`).textContent = formatValue(name, safeValue);
    if (updateSlider) {
        document.getElementById(`slider-${name}`).value = valueToSlider(name, safeValue);
    }
}

function syncSliderFromValue(name) {
    const input = document.getElementById(`val-${name}`);
    const value = parseFloat(input.value);
    if (!Number.isFinite(value)) return;
    setParamValue(name, value, true);
}

function updateBoundsForParam(name) {
    const slider = document.getElementById(`slider-${name}`);
    let min = parseFloat(document.getElementById(`min-${name}`).value);
    let max = parseFloat(document.getElementById(`max-${name}`).value);
    if (!Number.isFinite(min)) min = paramBounds[name].min;
    if (!Number.isFinite(max)) max = paramBounds[name].max;
    if (paramBounds[name].log) {
        min = Math.max(min, 1e-30);
        max = Math.max(max, min * 10);
    }
    if (max <= min) max = min + Math.max(Math.abs(min), 1);

    document.getElementById(`min-${name}`).value = min;
    document.getElementById(`max-${name}`).value = max;
    slider.min = paramBounds[name].log ? Math.log10(min) : min;
    slider.max = paramBounds[name].log ? Math.log10(max) : max;
    syncSliderFromValue(name);
    schedulePreview();
}

function getCurrentParams() {
    const params = {};
    const bounds = {};
    const fixed = {};
    for (const name of Object.keys(defaultParams)) {
        params[name] = parseFloat(document.getElementById(`val-${name}`).value);
        bounds[name] = {
            min: parseFloat(document.getElementById(`min-${name}`).value),
            max: parseFloat(document.getElementById(`max-${name}`).value)
        };
        fixed[name] = document.getElementById(`fixed-${name}`).checked;
    }
    return { params, bounds, fixed };
}

function initChart() {
    const ctx = document.getElementById('jvChart').getContext('2d');
    chart = new Chart(ctx, {
        type: 'scatter',
        data: {
            datasets: [
                {
                    label: '实验数据',
                    data: [],
                    borderColor: '#2563eb',
                    backgroundColor: 'rgba(37, 99, 235, 0.75)',
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    showLine: false,
                    fill: false
                },
                {
                    label: '模型曲线',
                    data: [],
                    borderColor: '#dc2626',
                    backgroundColor: 'rgba(220, 38, 38, 0.1)',
                    borderWidth: 2,
                    pointRadius: 0,
                    showLine: true,
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: {
                title: {
                    display: true,
                    text: 'J-V Curve Analysis',
                    font: { size: 18, weight: 'bold' }
                },
                legend: { position: 'top' }
            },
            scales: {
                x: {
                    type: 'linear',
                    position: 'bottom',
                    title: { display: true, text: 'Voltage (V)', font: { size: 14 } },
                    grid: { color: 'rgba(0,0,0,0.06)' }
                },
                y: {
                    type: 'linear',
                    title: { display: true, text: 'Current Density (mA/cm²)', font: { size: 14 } },
                    grid: { color: 'rgba(0,0,0,0.06)' }
                }
            }
        }
    });
}

function updateChart(V, JExp, JFit = null) {
    chart.data.datasets[0].data = V.map((v, i) => ({ x: v, y: JExp[i] }));
    chart.data.datasets[1].data = JFit ? V.map((v, i) => ({ x: v, y: JFit[i] })) : [];
    chart.update('none');
}

function setResultText(data, prefix = '') {
    let resultText = `${prefix}RMSE: ${data.rmse.toFixed(6)}\n\n`;
    for (const [name, val] of Object.entries(data.params)) {
        resultText += `${name}: ${formatValue(name, val)}`;
        if (data.fixed && data.fixed[name]) resultText += ' [锁定]';
        resultText += '\n';
    }
    document.getElementById('resultContainer').textContent = resultText;
}

function updateInputsFromParams(params) {
    for (const [name, val] of Object.entries(params)) {
        setParamValue(name, val, true);
    }
}

function parseAndPreviewUploadedCsv() {
    const lines = currentCSV.split(/\r?\n/).filter(line => line.trim());
    const data = [];
    for (let i = 1; i < lines.length; i++) {
        const parts = lines[i].split(',').map(v => parseFloat(v.trim()));
        if (Number.isFinite(parts[0]) && Number.isFinite(parts[1])) {
            data.push(parts);
        }
    }
    const V = data.map(d => d[0]);
    let J = data.map(d => d[1]);
    const meanJ = J.reduce((a, b) => a + b, 0) / Math.max(J.length, 1);
    if (meanJ > 0) J = J.map(j => -j);
    updateChart(V, J.map(j => -j));
    schedulePreview(0);
}

function schedulePreview(delay = 140) {
    window.clearTimeout(previewTimer);
    if (!currentCSV) return;
    previewTimer = window.setTimeout(runPreview, delay);
}

async function runPreview() {
    if (!currentCSV) return;
    if (previewController) previewController.abort();
    previewController = new AbortController();
    const { params, bounds } = getCurrentParams();

    try {
        const res = await fetch('/api/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ csv: currentCSV, params, bounds }),
            signal: previewController.signal
        });
        const data = await res.json();
        if (!data.success) return;
        updateChart(data.V, data.J_exp, data.J_fit);
        setResultText(data, '[预览] ');
    } catch (err) {
        if (err.name !== 'AbortError') {
            console.warn('Preview failed:', err);
        }
    }
}

document.getElementById('csvFile').addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (!file) return;
    document.getElementById('fileName').textContent = file.name;
    const reader = new FileReader();
    reader.onload = function(event) {
        currentCSV = event.target.result;
        parseAndPreviewUploadedCsv();
    };
    reader.readAsText(file);
});

document.getElementById('fitBtn').addEventListener('click', async function() {
    if (!currentCSV) {
        alert('请先导入 CSV 文件。');
        return;
    }
    const { params, bounds, fixed } = getCurrentParams();
    const options = {
        use_global: document.getElementById('useGlobal').checked,
        use_nelder: document.getElementById('useNelder').checked,
        use_log: document.getElementById('useLog').checked
    };

    const btn = document.getElementById('fitBtn');
    const progress = document.getElementById('progress');
    btn.disabled = true;
    btn.textContent = '拟合中...';
    progress.classList.remove('hidden');

    try {
        const res = await fetch('/api/fit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ csv: currentCSV, params, bounds, fixed, options })
        });
        const data = await res.json();
        if (data.success) {
            lastResult = data;
            updateChart(data.V, data.J_exp, data.J_fit);
            setResultText(data);
            updateInputsFromParams(data.params);
            document.getElementById('exportParams').disabled = false;
            document.getElementById('exportCSV').disabled = false;
        } else {
            alert('拟合失败: ' + data.error);
        }
    } catch (err) {
        alert('请求失败: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '开始拟合';
        progress.classList.add('hidden');
    }
});

document.getElementById('exportParams').addEventListener('click', function() {
    if (!lastResult) return;
    const text = document.getElementById('resultContainer').textContent;
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'params.txt';
    a.click();
    URL.revokeObjectURL(url);
});

document.getElementById('exportCSV').addEventListener('click', function() {
    if (!lastResult) return;
    let csv = 'V,J_Exp,J_Fit\n';
    for (let i = 0; i < lastResult.V.length; i++) {
        csv += `${lastResult.V[i]},${lastResult.J_exp[i]},${lastResult.J_fit[i]}\n`;
    }
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'fit_result.csv';
    a.click();
    URL.revokeObjectURL(url);
});

document.addEventListener('DOMContentLoaded', function() {
    initParams();
    initChart();
});
