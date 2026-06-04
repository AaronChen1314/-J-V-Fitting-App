const PARAM_NAMES = ['Jph', 'J01', 'J02', 'n1', 'n2', 'Rs', 'Rsh'];
const LOG_PARAMS = new Set(['J01', 'J02']);
const T = 300.0;
const KB = 1.380649e-23;
const QE = 1.602176634e-19;
const VT = (KB * T) / QE;

function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
}

function parseCsv(csv) {
    const lines = csv.split(/\r?\n/).filter(line => line.trim());
    if (lines.length < 2) throw new Error('CSV must contain a header and data rows.');
    const header = lines[0].split(',').map(v => v.trim().toLowerCase());
    let vIdx = header.findIndex(c => c.includes('volt') || c === 'v');
    let jIdx = header.findIndex(c => c.includes('curr') || c === 'j');
    if (vIdx < 0) vIdx = 0;
    if (jIdx < 0) jIdx = vIdx === 0 ? 1 : 0;

    const rows = [];
    for (let i = 1; i < lines.length; i++) {
        const parts = lines[i].split(',').map(v => Number.parseFloat(v.trim()));
        if (Number.isFinite(parts[vIdx]) && Number.isFinite(parts[jIdx])) {
            rows.push([parts[vIdx], parts[jIdx]]);
        }
    }
    if (rows.length < 3) throw new Error('At least 3 valid V-J points are required.');
    rows.sort((a, b) => a[0] - b[0]);

    const V = rows.map(row => row[0]);
    let J = rows.map(row => row[1]);
    const meanJ = J.reduce((sum, value) => sum + value, 0) / J.length;
    if (meanJ > 0) J = J.map(value => -value);
    return { V, J };
}

function estimateJscAtZero(V, J) {
    for (let i = 0; i < V.length; i++) {
        if (Math.abs(V[i]) < 1e-12) return Math.max(-J[i], 1e-9);
    }
    for (let i = 0; i < V.length - 1; i++) {
        if (V[i] <= 0 && V[i + 1] >= 0 && V[i + 1] !== V[i]) {
            const j0 = J[i] + (0 - V[i]) * (J[i + 1] - J[i]) / (V[i + 1] - V[i]);
            return Math.max(-j0, 1e-9);
        }
    }
    let best = 0;
    for (let i = 1; i < V.length; i++) {
        if (Math.abs(V[i]) < Math.abs(V[best])) best = i;
    }
    return Math.max(-J[best], 1e-9);
}

function estimateVoc(V, J) {
    for (let i = 0; i < J.length - 1; i++) {
        if ((J[i] <= 0 && J[i + 1] >= 0) || (J[i] >= 0 && J[i + 1] <= 0)) {
            if (J[i + 1] !== J[i]) {
                return V[i] - J[i] * (V[i + 1] - V[i]) / (J[i + 1] - J[i]);
            }
        }
    }
    let best = 0;
    for (let i = 1; i < J.length; i++) {
        if (Math.abs(J[i]) < Math.abs(J[best])) best = i;
    }
    return V[best];
}

function normalizeParam(name, value, min, max) {
    if (LOG_PARAMS.has(name)) {
        const lo = Math.log10(Math.max(min, 1e-30));
        const hi = Math.log10(Math.max(max, min * 10, 1e-29));
        return (Math.log10(Math.max(value, 1e-30)) - lo) / (hi - lo);
    }
    return (value - min) / (max - min);
}

function denormalizeParam(name, value, min, max) {
    const t = clamp(value, 0, 1);
    if (LOG_PARAMS.has(name)) {
        const lo = Math.log10(Math.max(min, 1e-30));
        const hi = Math.log10(Math.max(max, min * 10, 1e-29));
        return 10 ** (lo + t * (hi - lo));
    }
    return min + t * (max - min);
}

function buildInputs(params, bounds, fixed) {
    const freeNames = [];
    const x0 = [];
    const full = {};
    const cleanBounds = {};

    for (const name of PARAM_NAMES) {
        let min = Number(bounds?.[name]?.min);
        let max = Number(bounds?.[name]?.max);
        let value = Number(params?.[name]);
        if (!Number.isFinite(min)) min = name === 'Jph' ? 1e-9 : 0;
        if (!Number.isFinite(max) || max <= min) max = min + Math.max(Math.abs(min), 1);
        if (LOG_PARAMS.has(name)) {
            min = Math.max(min, 1e-30);
            max = Math.max(max, min * 10);
        }
        if (!Number.isFinite(value)) value = (min + max) / 2;
        value = clamp(value, min, max);
        full[name] = value;
        cleanBounds[name] = { min, max };
        if (!fixed?.[name]) {
            freeNames.push(name);
            x0.push(clamp(normalizeParam(name, value, min, max), 0, 1));
        }
    }
    return { freeNames, x0, full, cleanBounds };
}

function reconstruct(x, freeNames, full, bounds) {
    const params = { ...full };
    for (let i = 0; i < freeNames.length; i++) {
        const name = freeNames[i];
        params[name] = denormalizeParam(name, x[i], bounds[name].min, bounds[name].max);
    }
    return params;
}

function solveCurrentAtVoltage(V, p, guess) {
    const JphA = p.Jph * 1e-3;
    const J01A = p.J01 * 1e-3;
    const J02A = p.J02 * 1e-3;
    const Rs = Math.max(p.Rs, 0);
    const Rsh = Math.max(p.Rsh, 1e-2);
    const n1 = Math.max(p.n1, 1e-6);
    const n2 = Math.max(p.n2, 1e-6);
    let J = Number.isFinite(guess) ? guess : -JphA;

    for (let iter = 0; iter < 30; iter++) {
        const Vi = V - J * Rs;
        const a1 = clamp(Vi / (n1 * VT), -100, 100);
        const a2 = clamp(Vi / (n2 * VT), -100, 100);
        const e1 = Math.exp(a1);
        const e2 = Math.exp(a2);
        const f = J + JphA - J01A * (e1 - 1) - J02A * (e2 - 1) - Vi / Rsh;
        const df = 1 + (J01A * e1 * Rs) / (n1 * VT) + (J02A * e2 * Rs) / (n2 * VT) + Rs / Rsh;
        const step = f / Math.max(df, 1e-30);
        J -= step;
        if (!Number.isFinite(J)) return guess;
        if (Math.abs(step) < 1e-11) break;
    }
    return J;
}

function doubleDiodeModel(V, p) {
    const result = [];
    let guess = -p.Jph * 1e-3;
    for (const voltage of V) {
        guess = solveCurrentAtVoltage(voltage, p, guess);
        result.push(guess * 1e3);
    }
    return result;
}

function rawRmse(J, model) {
    let sum = 0;
    for (let i = 0; i < J.length; i++) {
        const diff = J[i] - model[i];
        sum += diff * diff;
    }
    return Math.sqrt(sum / J.length);
}

function logRmse(J, model) {
    const eps = 1e-6;
    let sum = 0;
    for (let i = 0; i < J.length; i++) {
        const diff = Math.log10(Math.abs(J[i]) + eps) - Math.log10(Math.abs(model[i]) + eps);
        sum += diff * diff;
    }
    return Math.sqrt(sum / J.length);
}

function optimize(V, J, base, mode) {
    const { freeNames, x0, full, cleanBounds } = base;
    if (!freeNames.length) {
        const params = { ...full };
        const model = doubleDiodeModel(V, params);
        return { params, model, rmse: rawRmse(J, model), logRmse: logRmse(J, model), score: rawRmse(J, model) };
    }

    const scale = Math.max(...J.map(v => Math.abs(v)), 1);
    function cost(x) {
        const params = reconstruct(x, freeNames, full, cleanBounds);
        const model = doubleDiodeModel(V, params);
        let sum = 0;
        for (let i = 0; i < J.length; i++) {
            let residual;
            if (mode === 'log') {
                residual = Math.log10(Math.abs(model[i]) + 1e-6) - Math.log10(Math.abs(J[i]) + 1e-6);
            } else {
                residual = (model[i] - J[i]) / scale;
            }
            sum += residual * residual;
        }
        return sum;
    }

    let best = x0.slice();
    let bestCost = cost(best);
    let steps = best.map(() => 0.18);
    const maxPasses = mode === 'log' ? 20 : 24;

    for (let pass = 0; pass < maxPasses; pass++) {
        let improved = false;
        for (let i = 0; i < best.length; i++) {
            for (const direction of [1, -1]) {
                const candidate = best.slice();
                candidate[i] = clamp(candidate[i] + direction * steps[i], 0, 1);
                const candidateCost = cost(candidate);
                if (candidateCost < bestCost) {
                    best = candidate;
                    bestCost = candidateCost;
                    improved = true;
                }
            }
        }
        if (!improved) steps = steps.map(step => step * 0.55);
        if (Math.max(...steps) < 0.0005) break;
        if (pass % 4 === 0) postMessage({ type: 'progress', message: `${mode} fitting ${pass + 1}/${maxPasses}` });
    }

    best = nelderMead(cost, best, mode === 'log' ? 80 : 110);

    const params = reconstruct(best, freeNames, full, cleanBounds);
    const model = doubleDiodeModel(V, params);
    return {
        params,
        model,
        rmse: rawRmse(J, model),
        logRmse: logRmse(J, model),
        score: rawRmse(J, model) / scale + (mode === 'log' ? 0.15 : 0.05) * logRmse(J, model),
        mode
    };
}

function nelderMead(cost, start, maxIter) {
    const n = start.length;
    if (!n) return start;
    let simplex = [start.slice()];
    for (let i = 0; i < n; i++) {
        const point = start.slice();
        point[i] = clamp(point[i] + 0.035, 0, 1);
        simplex.push(point);
    }
    let values = simplex.map(point => cost(point));

    for (let iter = 0; iter < maxIter; iter++) {
        const order = values.map((value, index) => ({ value, index })).sort((a, b) => a.value - b.value);
        simplex = order.map(item => simplex[item.index]);
        values = order.map(item => item.value);

        const bestValue = values[0];
        const worstValue = values[n];
        if (Math.abs(worstValue - bestValue) < 1e-9) break;

        const centroid = new Array(n).fill(0);
        for (let i = 0; i < n; i++) {
            for (let j = 0; j < n; j++) centroid[j] += simplex[i][j] / n;
        }

        const reflected = centroid.map((c, j) => clamp(c + (c - simplex[n][j]), 0, 1));
        const reflectedValue = cost(reflected);

        if (reflectedValue < values[0]) {
            const expanded = centroid.map((c, j) => clamp(c + 2 * (reflected[j] - c), 0, 1));
            const expandedValue = cost(expanded);
            simplex[n] = expandedValue < reflectedValue ? expanded : reflected;
            values[n] = Math.min(expandedValue, reflectedValue);
        } else if (reflectedValue < values[n - 1]) {
            simplex[n] = reflected;
            values[n] = reflectedValue;
        } else {
            const contracted = centroid.map((c, j) => clamp(c + 0.5 * (simplex[n][j] - c), 0, 1));
            const contractedValue = cost(contracted);
            if (contractedValue < values[n]) {
                simplex[n] = contracted;
                values[n] = contractedValue;
            } else {
                for (let i = 1; i <= n; i++) {
                    simplex[i] = simplex[0].map((value, j) => clamp(value + 0.5 * (simplex[i][j] - value), 0, 1));
                    values[i] = cost(simplex[i]);
                }
            }
        }
    }

    const bestIndex = values.indexOf(Math.min(...values));
    return simplex[bestIndex];
}

function fitLocally(payload) {
    const { V, J } = parseCsv(payload.csv);
    const base = buildInputs(payload.params, payload.bounds, payload.fixed);
    const bases = [base];
    if (payload.options?.use_global) bases.push(...makeSearchBases(base));
    const candidates = [];
    for (const candidateBase of bases) {
        candidates.push(optimize(V, J, candidateBase, 'linear'));
        if (payload.options?.use_log) candidates.push(optimize(V, J, candidateBase, 'log'));
    }
    candidates.sort((a, b) => a.score - b.score);
    const best = candidates[0];
    const meta = {
        Jsc: estimateJscAtZero(V, J),
        Voc: estimateVoc(V, J),
        mode: best.mode || 'linear',
        candidates: candidates.map(c => ({ mode: c.mode, rmse: c.rmse, logRmse: c.logRmse, score: c.score }))
    };
    return {
        success: true,
        params: best.params,
        V,
        J_exp: J.map(value => -value),
        J_fit: best.model.map(value => -value),
        rmse: best.rmse,
        fixed: payload.fixed || {},
        meta
    };
}

function makeSearchBases(base) {
    const offsets = [
        [0.18, -0.12, 0.10, -0.08, 0.14, -0.16, 0.12],
        [-0.16, 0.14, -0.10, 0.12, -0.08, 0.18, -0.12],
        [0.30, -0.25, 0.22, -0.20, 0.18, -0.24, 0.16],
        [-0.28, 0.22, -0.20, 0.18, -0.22, 0.26, -0.18],
    ];
    return offsets.map(offset => ({
        ...base,
        x0: base.x0.map((value, index) => clamp(value + offset[index % offset.length], 0.02, 0.98)),
        full: { ...base.full },
        cleanBounds: { ...base.cleanBounds },
        freeNames: base.freeNames.slice(),
    }));
}

self.onmessage = event => {
    try {
        if (event.data?.type !== 'fit') return;
        postMessage({ type: 'progress', message: 'local fitting started' });
        const result = fitLocally(event.data.payload);
        postMessage({ type: 'result', result });
    } catch (error) {
        postMessage({ type: 'error', error: error.message || String(error) });
    }
};
