from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit, differential_evolution, fsolve, least_squares, minimize
from scipy.constants import k as k_B, e as q_e
import io

app = Flask(__name__)
CORS(app)

T = 300.0
Vt = (k_B * T) / q_e

PARAM_NAMES = ['Jph', 'J01', 'J02', 'n1', 'n2', 'Rs', 'Rsh']
LOG_PARAMS = {'J01', 'J02'}


def double_diode_model(V_array, Jph, J01, J02, n1, n2, Rs, Rsh):
    J_calc = []
    Jph_A = Jph * 1e-3
    J01_A = J01 * 1e-3
    J02_A = J02 * 1e-3
    Rsh = max(Rsh, 1e-2)
    n1 = max(n1, 1e-6)
    n2 = max(n2, 1e-6)

    current_guess = -Jph_A
    for V in np.asarray(V_array, dtype=float):
        def equation_to_solve(J):
            V_internal = V - J * Rs
            exp1 = np.exp(np.clip(V_internal / (n1 * Vt), -100, 100))
            exp2 = np.exp(np.clip(V_internal / (n2 * Vt), -100, 100))
            term_d1 = J01_A * (exp1 - 1)
            term_d2 = J02_A * (exp2 - 1)
            term_sh = V_internal / Rsh
            return J + Jph_A - term_d1 - term_d2 - term_sh

        try:
            J_solution, = fsolve(equation_to_solve, current_guess, xtol=1e-9, maxfev=100)
            if not np.isfinite(J_solution):
                J_solution = current_guess
        except Exception:
            J_solution = current_guess
        current_guess = J_solution
        J_calc.append(J_solution)
    return np.array(J_calc) * 1e3


def parse_jv_csv(csv_content):
    df = pd.read_csv(io.StringIO(csv_content))
    cols = [c.lower() for c in df.columns]
    v_idx = next(i for i, c in enumerate(cols) if 'volt' in c or c.strip() == 'v')
    j_idx = next(i for i, c in enumerate(cols) if 'curr' in c or c.strip() == 'j')

    V_data = pd.to_numeric(df.iloc[:, v_idx], errors='coerce').to_numpy()
    J_data_mA = pd.to_numeric(df.iloc[:, j_idx], errors='coerce').to_numpy()
    mask = np.isfinite(V_data) & np.isfinite(J_data_mA)
    V_data = V_data[mask]
    J_data_mA = J_data_mA[mask]
    if len(V_data) < 3:
        raise ValueError('有效数据点不足，至少需要 3 个 V-J 数据点。')

    order = np.argsort(V_data)
    V_data = V_data[order]
    J_data_mA = J_data_mA[order]

    # 与 V5 桌面版一致：内部使用负电流，绘图和导出时再取反。
    if np.mean(J_data_mA) > 0:
        J_data_mA = -J_data_mA
    return V_data, J_data_mA


def estimate_defaults(J_data_mA):
    Jsc = max(float(-np.min(J_data_mA)), 1e-9)
    defaults = {
        'Jph': Jsc,
        'J01': 1e-12,
        'J02': 1e-8,
        'n1': 1.0,
        'n2': 2.0,
        'Rs': 1.0,
        'Rsh': 2000.0,
    }
    bounds = {
        'Jph': (Jsc * 0.9, Jsc * 1.1),
        'J01': (1e-20, 1e-5),
        'J02': (1e-15, 1e-3),
        'n1': (0.8, 1.3),
        'n2': (1.4, 3.0),
        'Rs': (0.01, 20.0),
        'Rsh': (100.0, 100000.0),
    }
    return defaults, bounds


def build_fit_inputs(J_data_mA, request_params, request_bounds):
    defaults, default_bounds = estimate_defaults(J_data_mA)
    request_params = request_params or {}
    request_bounds = request_bounds or {}
    p0, b_min, b_max = [], [], []

    for name in PARAM_NAMES:
        lo, hi = default_bounds[name]
        item_bounds = request_bounds.get(name, {})
        try:
            lo = float(item_bounds.get('min', lo))
            hi = float(item_bounds.get('max', hi))
        except (TypeError, ValueError):
            pass

        if name in LOG_PARAMS:
            lo = max(lo, 1e-30)
            hi = max(hi, lo * 10)
        if hi <= lo:
            hi = lo + max(abs(lo), 1.0)

        try:
            val = float(request_params.get(name, defaults[name]))
        except (TypeError, ValueError):
            val = defaults[name]
        if name in LOG_PARAMS:
            val = max(val, lo)
        p0.append(float(np.clip(val, lo, hi)))
        b_min.append(lo)
        b_max.append(hi)

    return np.array(p0), np.array(b_min), np.array(b_max)


def to_optimizer_space(params, names):
    values = np.array(params, dtype=float).copy()
    for i, name in enumerate(names):
        if name in LOG_PARAMS:
            values[i] = np.log10(max(values[i], 1e-30))
    return values


def from_optimizer_space(values, names):
    params = np.array(values, dtype=float).copy()
    for i, name in enumerate(names):
        if name in LOG_PARAMS:
            params[i] = 10 ** params[i]
    return params


def rmse(J_data_mA, J_model):
    return float(np.sqrt(np.mean((J_data_mA - J_model) ** 2)))


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/preview', methods=['POST'])
def preview():
    try:
        data = request.json or {}
        V_data, J_data_mA = parse_jv_csv(data.get('csv', ''))
        p0, _, _ = build_fit_inputs(J_data_mA, data.get('params'), data.get('bounds'))
        J_preview = double_diode_model(V_data, *p0)
        return jsonify({
            'success': True,
            'params': dict(zip(PARAM_NAMES, p0.tolist())),
            'V': V_data.tolist(),
            'J_exp': (-J_data_mA).tolist(),
            'J_fit': (-J_preview).tolist(),
            'rmse': rmse(J_data_mA, J_preview),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/fit', methods=['POST'])
def fit():
    try:
        data = request.json or {}
        V_data, J_data_mA = parse_jv_csv(data.get('csv', ''))
        p0, b_min, b_max = build_fit_inputs(
            J_data_mA,
            data.get('params'),
            data.get('bounds'),
        )

        fixed = data.get('fixed', {}) or {}
        options = data.get('options', {}) or {}
        fixed_flags = np.array([fixed.get(name, False) for name in PARAM_NAMES], dtype=bool)

        idx_free = np.where(~fixed_flags)[0]
        idx_fixed = np.where(fixed_flags)[0]

        if len(idx_free) == 0:
            J_final = double_diode_model(V_data, *p0)
            return jsonify({
                'success': True,
                'params': dict(zip(PARAM_NAMES, p0.tolist())),
                'V': V_data.tolist(),
                'J_exp': (-J_data_mA).tolist(),
                'J_fit': (-J_final).tolist(),
                'rmse': rmse(J_data_mA, J_final),
                'fixed': fixed,
            })

        free_names = [PARAM_NAMES[i] for i in idx_free]
        p0_free = to_optimizer_space(p0[idx_free], free_names)
        b_min_free = to_optimizer_space(b_min[idx_free], free_names)
        b_max_free = to_optimizer_space(b_max[idx_free], free_names)
        vals_fixed = p0[idx_fixed]

        def reconstruct_full_params(params_free_opt):
            params_full = np.zeros_like(p0)
            params_full[idx_fixed] = vals_fixed
            params_full[idx_free] = from_optimizer_space(params_free_opt, free_names)
            return params_full

        use_global = bool(options.get('use_global', False))
        use_nelder = bool(options.get('use_nelder', True))
        use_log = bool(options.get('use_log', False))

        def residual_func(params_free):
            p_full = reconstruct_full_params(params_free)
            J_model = double_diode_model(V_data, *p_full)
            if use_log:
                epsilon = 1e-6
                return np.log10(np.abs(J_model) + epsilon) - np.log10(np.abs(J_data_mA) + epsilon)
            return J_model - J_data_mA

        def cost_func(params_free):
            if np.any(params_free < b_min_free) or np.any(params_free > b_max_free):
                return 1e20
            residuals = residual_func(params_free)
            return float(np.sum(residuals ** 2))

        final_params_free = p0_free.copy()

        if use_global:
            result = differential_evolution(
                cost_func,
                list(zip(b_min_free, b_max_free)),
                strategy='best1bin',
                maxiter=50,
                popsize=10,
                workers=1,
                polish=False,
            )
            final_params_free = result.x

        if use_nelder:
            res = minimize(
                cost_func,
                final_params_free,
                method='Nelder-Mead',
                tol=1e-5,
                options={'maxiter': 2000},
            )
            final_params_free = np.clip(res.x, b_min_free, b_max_free)

        # V5 的 curve_fit 思路在这里升级为有界 least_squares 精修；
        # 若 least_squares 失败，再回退到 curve_fit。
        try:
            lsq = least_squares(
                residual_func,
                final_params_free,
                bounds=(b_min_free, b_max_free),
                loss='soft_l1',
                f_scale=0.1 if use_log else 1.0,
                max_nfev=2500,
                xtol=1e-9,
                ftol=1e-9,
                gtol=1e-9,
            )
            final_params_free = lsq.x
        except Exception:
            def model_wrapper_for_curve_fit(v, *args_free):
                return double_diode_model(v, *reconstruct_full_params(np.array(args_free)))

            try:
                popt, _ = curve_fit(
                    model_wrapper_for_curve_fit,
                    V_data,
                    J_data_mA,
                    p0=final_params_free,
                    bounds=(b_min_free, b_max_free),
                    max_nfev=2500,
                )
                final_params_free = popt
            except Exception:
                pass

        final_params_full = reconstruct_full_params(final_params_free)
        J_final = double_diode_model(V_data, *final_params_full)
        return jsonify({
            'success': True,
            'params': dict(zip(PARAM_NAMES, final_params_full.tolist())),
            'V': V_data.tolist(),
            'J_exp': (-J_data_mA).tolist(),
            'J_fit': (-J_final).tolist(),
            'rmse': rmse(J_data_mA, J_final),
            'fixed': fixed,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
