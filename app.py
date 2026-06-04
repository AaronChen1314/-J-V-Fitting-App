from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit, fsolve, differential_evolution, minimize
from scipy.constants import k as k_B, e as q_e
import io
import base64

app = Flask(__name__)
CORS(app)

T = 300.0
Vt = (k_B * T) / q_e


def double_diode_model(V_array, Jph, J01, J02, n1, n2, Rs, Rsh):
    J_calc = []
    Jph_A = Jph * 1e-3
    J01_A = J01 * 1e-3
    J02_A = J02 * 1e-3

    if Rsh < 1e-2:
        Rsh = 1e-2

    current_guess = -Jph_A

    for V in V_array:
        def equation_to_solve(J):
            V_internal = V - J * Rs

            def safe_exp(val):
                if val > 100:
                    return 1e43
                if val < -100:
                    return 0.0
                return np.exp(val)

            term_d1 = J01_A * (safe_exp(V_internal / (n1 * Vt)) - 1)
            term_d2 = J02_A * (safe_exp(V_internal / (n2 * Vt)) - 1)
            term_sh = V_internal / Rsh
            return J + Jph_A - term_d1 - term_d2 - term_sh

        try:
            J_solution, = fsolve(equation_to_solve, current_guess, xtol=1e-8)
            current_guess = J_solution
        except:
            J_solution = -Jph_A
        J_calc.append(J_solution)
    return np.array(J_calc) * 1e3


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/fit', methods=['POST'])
def fit():
    try:
        data = request.json
        csv_content = data.get('csv')
        params = data.get('params', {})
        fixed = data.get('fixed', {})
        options = data.get('options', {})

        df = pd.read_csv(io.StringIO(csv_content))
        cols = [c.lower() for c in df.columns]
        v_idx = next(i for i, c in enumerate(cols) if "volt" in c or "v" == c.strip())
        j_idx = next(i for i, c in enumerate(cols) if "curr" in c or "j" == c.strip())
        V_data = df.iloc[:, v_idx].values
        J_data_mA = df.iloc[:, j_idx].values

        # 完全按照原始tkinter代码的逻辑：如果电流平均值>0，将电流取反
        if np.mean(J_data_mA) > 0:
            J_data_mA = -J_data_mA

        # 计算短路电流密度：取J_data_mA最小值的负值（因为J_data_mA已经是处理后的值）
        Jsc = -np.min(J_data_mA)
        defaults = {
            'Jph': Jsc,
            'J01': 1e-12,
            'J02': 1e-8,
            'n1': 1.0,
            'n2': 2.0,
            'Rs': 1.0,
            'Rsh': 2000.0
        }

        bounds_defaults = {
            'Jph': (Jsc * 0.9, Jsc * 1.1),
            'J01': (1e-20, 1e-5),
            'J02': (1e-15, 1e-3),
            'n1': (0.8, 1.4),
            'n2': (1.5, 3.0),
            'Rs': (0.01, 50.0),
            'Rsh': (100.0, 100000.0)
        }

        p0 = []
        b_min = []
        b_max = []
        param_names = ['Jph', 'J01', 'J02', 'n1', 'n2', 'Rs', 'Rsh']
        for name in param_names:
            if name in params:
                p0.append(float(params[name]))
            else:
                p0.append(defaults[name])
            b_min.append(bounds_defaults[name][0])
            b_max.append(bounds_defaults[name][1])

        fixed_flags = [fixed.get(name, False) for name in param_names]

        idx_free = np.where(~np.array(fixed_flags, dtype=bool))[0]
        idx_fixed = np.where(np.array(fixed_flags, dtype=bool))[0]

        if len(idx_free) == 0:
            J_final = double_diode_model(V_data, *p0)
            rmse = np.sqrt(np.mean((J_data_mA - J_final)**2))
            return jsonify({
                'success': True,
                'params': dict(zip(param_names, p0)),
                'V': V_data.tolist(),
                'J_exp': (-J_data_mA).tolist(),
                'J_fit': (-J_final).tolist(),
                'rmse': float(rmse)
            })

        p0_free = np.array(p0)[idx_free]
        b_min_free = np.array(b_min)[idx_free]
        b_max_free = np.array(b_max)[idx_free]
        vals_fixed = np.array(p0)[idx_fixed]

        def reconstruct_full_params(params_free):
            params_full = np.zeros_like(p0)
            params_full[idx_fixed] = vals_fixed
            params_full[idx_free] = params_free
            return params_full

        use_global = options.get('use_global', False)
        use_nelder = options.get('use_nelder', True)
        use_log = options.get('use_log', False)

        def cost_func(params_free):
            if use_nelder:
                for i, val in enumerate(params_free):
                    if val < b_min_free[i] or val > b_max_free[i]:
                        return 1e20
            p_full = reconstruct_full_params(params_free)
            J_model = double_diode_model(V_data, *p_full)
            if use_log:
                epsilon = 1e-6
                log_exp = np.log10(np.abs(J_data_mA) + epsilon)
                log_mod = np.log10(np.abs(J_model) + epsilon)
                return np.sum((log_exp - log_mod)**2)
            else:
                return np.sum((J_data_mA - J_model)**2)

        final_params_free = p0_free

        if use_global:
            de_bounds_free = list(zip(b_min_free, b_max_free))
            result = differential_evolution(
                cost_func,
                de_bounds_free,
                strategy='best1bin',
                maxiter=50,
                popsize=10,
                workers=1
            )
            final_params_free = result.x

        if use_nelder:
            res = minimize(
                cost_func,
                final_params_free,
                method='Nelder-Mead',
                tol=1e-5,
                options={'maxiter': 2000}
            )
            final_params_free = res.x

        final_params_full = reconstruct_full_params(final_params_free)
        J_final = double_diode_model(V_data, *final_params_full)
        rmse = np.sqrt(np.mean((J_data_mA - J_final)**2))

        # 按照原始tkinter代码的逻辑：绘图时使用-J_data_mA和-J_fit_mA
        return jsonify({
            'success': True,
            'params': dict(zip(param_names, final_params_full.tolist())),
            'V': V_data.tolist(),
            'J_exp': (-J_data_mA).tolist(),
            'J_fit': (-J_final).tolist(),
            'rmse': float(rmse),
            'fixed': fixed
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
