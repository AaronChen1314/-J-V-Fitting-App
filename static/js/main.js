let chart = null;
let currentCSV = null;
let lastResult = null;

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
    Jph: { min: 0, max: 50 },
    J01: { min: 1e-20, max: 1e-5, log: true },
    J02: { min: 1e-15, max: 1e-3, log: true },
    n1: { min: 0.5, max: 2.0 },
    n2: { min: 1.0, max: 4.0 },
    Rs: { min: 0.01, max: 100 },
    Rsh: { min: 10, max: 1e6 }
};

function initParams() {
    const container = document.getElementById('paramContainer');
    container.innerHTML = '';
    for (const [name, val] of Object.entries(defaultParams)) {
        const bounds = paramBounds[name];
        const div = document.createElement('div');
        div.className = 'param-item';
        div.innerHTML = `
            <div class="param-header">
                <span class="param-name">${name}</span>
                <label class="fixed-checkbox">
                    <input type="checkbox" id="fixed-${name}">
                    <span>锁定</span>
                </label>
            </div>
            <input type="range" class="param-slider" id="slider-${name}" 
                   min="${bounds.log ? Math.log10(bounds.min) : bounds.min}"
                   max="${bounds.log ? Math.log10(bounds.max) : bounds.max}"
                   step="${bounds.log ? 0.1 : 0.01}"
                   value="${bounds.log ? Math.log10(val) : val}">
            <div class="param-inputs">
                <div class="param-input">
                    <label>Min</label>
                    <input type="text" id="min-${name}" value="${bounds.min}">
                </div>
                <div class="param-input">
                    <label>Max</label>
                    <input type="text" id="max-${name}" value="${bounds.max}">
                </div>
                <div class="param-input">
                    <label>Val</label>
                    <input type="text" id="val-${name}" value="${bounds.log ? val.toExponential(2) : val.toFixed(4)}">
                </div>
            </div>
        `;
        container.appendChild(div);
        document.getElementById(`slider-${name}`).addEventListener('input', () => updateParamValue(name));
        document.getElementById(`val-${name}`).addEventListener('change', () => updateSliderFromValue(name));
    }
}

function updateParamValue(name) {
    const slider = document.getElementById(`slider-${name}`);
    const valInput = document.getElementById(`val-${name}`);
    const bounds = paramBounds[name];
    let val = parseFloat(slider.value);
    if (bounds.log) val = Math.pow(10, val);
    valInput.value = bounds.log ? val.toExponential(2) : val.toFixed(4);
}

function updateSliderFromValue(name) {
    const slider = document.getElementById(`slider-${name}`);
    const valInput = document.getElementById(`val-${name}`);
    const bounds = paramBounds[name];
    let val = parseFloat(valInput.value);
    if (bounds.log) val = Math.log10(val);
    slider.value = val;
}

function getCurrentParams() {
    const params = {};
    const fixed = {};
    for (const name of Object.keys(defaultParams)) {
        const val = parseFloat(document.getElementById(`val-${name}`).value);
        params[name] = val;
        fixed[name] = document.getElementById(`fixed-${name}`).checked;
    }
    return { params, fixed };
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
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.8)',
                    pointRadius: 5,
                    pointHoverRadius: 7,
                    showLine: false,
                    fill: false
                },
                {
                    label: '拟合曲线',
                    data: [],
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    borderWidth: 3,
                    pointRadius: 0,
                    showLine: true,
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
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
                    grid: { color: 'rgba(0,0,0,0.05)' }
                },
                y: {
                    type: 'linear',
                    title: { display: true, text: 'Current Density (mA/cm²)', font: { size: 14 } },
                    grid: { color: 'rgba(0,0,0,0.05)' }
                }
            }
        }
    });
}

function updateChart(V, JExp, JFit = null) {
    chart.data.datasets[0].data = V.map((v, i) => ({ x: v, y: JExp[i] }));
    if (JFit) {
        chart.data.datasets[1].data = V.map((v, i) => ({ x: v, y: JFit[i] }));
    }
    chart.update();
}

document.getElementById('csvFile').addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (!file) return;
    document.getElementById('fileName').textContent = file.name;
    const reader = new FileReader();
    reader.onload = function(e) {
        currentCSV = e.target.result;
        const lines = currentCSV.split('\n').filter(l => l.trim());
        const data = [];
        
        // 解析数据，跳过表头
        for (let i = 1; i < lines.length; i++) {
            const parts = lines[i].split(',').map(v => parseFloat(v.trim()));
            if (!isNaN(parts[0]) && !isNaN(parts[1])) {
                data.push(parts);
            }
        }
        
        const V = data.map(d => d[0]);
        let J = data.map(d => d[1]);
        
        // 按照原始tkinter代码的逻辑处理
        const meanJ = J.reduce((a, b) => a + b, 0) / J.length;
        if (meanJ > 0) {
            J = J.map(j => -j);
        }
        // 绘图时再取反（按照原始代码的方式）
        updateChart(V, J.map(j => -j));
    };
    reader.readAsText(file);
});

document.getElementById('fitBtn').addEventListener('click', async function() {
    if (!currentCSV) {
        alert('请先导入 CSV 文件！');
        return;
    }
    const { params, fixed } = getCurrentParams();
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
            body: JSON.stringify({ csv: currentCSV, params, fixed, options })
        });
        const data = await res.json();
        if (data.success) {
            lastResult = data;
            updateChart(data.V, data.J_exp, data.J_fit);
            let resultText = `RMSE: ${data.rmse.toFixed(5)}\n\n`;
            for (const [name, val] of Object.entries(data.params)) {
                resultText += `${name}: ${val.toExponential(4)}`;
                if (data.fixed && data.fixed[name]) resultText += ' [锁]';
                resultText += '\n';
            }
            document.getElementById('resultContainer').textContent = resultText;
            document.getElementById('exportParams').disabled = false;
            document.getElementById('exportCSV').disabled = false;
            for (const [name, val] of Object.entries(data.params)) {
                const bounds = paramBounds[name];
                const slider = document.getElementById(`slider-${name}`);
                const valInput = document.getElementById(`val-${name}`);
                let sliderVal = val;
                if (bounds.log) sliderVal = Math.log10(val);
                slider.value = sliderVal;
                valInput.value = bounds.log ? val.toExponential(2) : val.toFixed(4);
            }
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
    const blob = new Blob([text], { type: 'text/plain' });
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
    const blob = new Blob([csv], { type: 'text/csv' });
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
