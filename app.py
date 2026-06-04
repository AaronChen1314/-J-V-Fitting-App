from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import io
import warnings

import numpy as np
import pandas as pd
from scipy.constants import e as q_e, k as k_B
from scipy.optimize import curve_fit, differential_evolution, fsolve, least_squares, minimize

app = Flask(__name__)
CORS(app)

T = 300.0
Vt = (k_B * T) / q_e

PARAM_NAMES = ["Jph", "J01", "J02", "n1", "n2", "Rs", "Rsh"]
LOG_PARAMS = {"J01", "J02"}


@app.errorhandler(Exception)
def handle_exception(error):
    if request.path.startswith("/api/"):
        status = 400 if isinstance(error, ValueError) else 500
        return jsonify({"success": False, "error": str(error)}), status
    raise error


def double_diode_model(V_array, Jph, J01, J02, n1, n2, Rs, Rsh):
    J_calc = []
    Jph_A = Jph * 1e-3
    J01_A = J01 * 1e-3
    J02_A = J02 * 1e-3
    Rs = max(float(Rs), 0.0)
    Rsh = max(float(Rsh), 1e-2)
    n1 = max(float(n1), 1e-6)
    n2 = max(float(n2), 1e-6)

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
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                J_solution, = fsolve(equation_to_solve, current_guess, xtol=1e-8, maxfev=80)
            if not np.isfinite(J_solution):
                J_solution = current_guess
        except Exception:
            J_solution = current_guess
        current_guess = J_solution
        J_calc.append(J_solution)
    return np.array(J_calc) * 1e3


def parse_jv_csv(csv_content):
    if not csv_content:
        raise ValueError("CSV 内容为空。")

    df = pd.read_csv(io.StringIO(csv_content))
    if df.shape[1] < 2:
        raise ValueError("CSV 至少需要两列：Voltage 和 Current/J。")

    cols = [str(c).strip().lower() for c in df.columns]
    v_candidates = [i for i, c in enumerate(cols) if "volt" in c or c == "v"]
    j_candidates = [i for i, c in enumerate(cols) if "curr" in c or c in {"j", "current", "current density"}]
    v_idx = v_candidates[0] if v_candidates else 0
    j_idx = j_candidates[0] if j_candidates else (1 if v_idx == 0 else 0)

    V_data = pd.to_numeric(df.iloc[:, v_idx], errors="coerce").to_numpy()
    J_data_mA = pd.to_numeric(df.iloc[:, j_idx], errors="coerce").to_numpy()
    mask = np.isfinite(V_data) & np.isfinite(J_data_mA)
    V_data = V_data[mask]
    J_data_mA = J_data_mA[mask]
    if len(V_data) < 3:
        raise ValueError("有效数据点不足，至少需要 3 个 V-J 数据点。")

    order = np.argsort(V_data)
    V_data = V_data[order]
    J_data_mA = J_data_mA[order]

    # 与 V5 桌面版一致：内部拟合使用负电流，绘图和导出时再取反。
    if np.nanmean(J_data_mA) > 0:
        J_data_mA = -J_data_mA
    return V_data, J_data_mA


def estimate_jsc_at_zero(V_data, J_data_mA):
    V = np.asarray(V_data, dtype=float)
    J = np.asarray(J_data_mA, dtype=float)
    if np.any(np.isclose(V, 0.0, atol=1e-12)):
        j0 = float(J[np.argmin(np.abs(V))])
    elif V[0] <= 0 <= V[-1]:
        j0 = float(np.interp(0.0, V, J))
    else:
        span = max(float(np.ptp(V)), 1e-9)
        near = np.abs(V) <= max(0.02, span * 0.03)
        if np.any(near):
            j0 = float(np.median(J[near]))
        else:
            j0 = float(J[np.argmin(np.abs(V))])
    return max(-j0, 1e-9)


def estimate_voc(V_data, J_data_mA):
    V = np.asarray(V_data, dtype=float)
    J = np.asarray(J_data_mA, dtype=float)
    sign_changes = np.where(np.diff(np.signbit(J)))[0]
    if len(sign_changes):
        i = sign_changes[0]
        if J[i + 1] != J[i]:
            return float(V[i] - J[i] * (V[i + 1] - V[i]) / (J[i + 1] - J[i]))
    return float(V[np.argmin(np.abs(J))])


def estimate_resistance(V_data, J_data_mA, region):
    V = np.asarray(V_data, dtype=float)
    J = np.asarray(J_data_mA, dtype=float)
    if len(V) < 5:
        return None
    if region == "near_zero":
        mask = np.abs(V) <= max(0.05, np.ptp(V) * 0.08)
    else:
        threshold = np.quantile(V, 0.8)
        mask = V >= threshold
    if np.count_nonzero(mask) < 3:
        return None
    try:
        slope = np.polyfit(V[mask], J[mask], 1)[0]
    except Exception:
        return None
    if not np.isfinite(slope) or abs(slope) < 1e-12:
        return None
    return abs(1000.0 / slope)


def estimate_defaults(V_data, J_data_mA):
    jsc = estimate_jsc_at_zero(V_data, J_data_mA)
    voc = estimate_voc(V_data, J_data_mA)
    rsh_guess = estimate_resistance(V_data, J_data_mA, "near_zero") or 2000.0
    rs_guess = estimate_resistance(V_data, J_data_mA, "forward") or 1.0

    rsh_guess = float(np.clip(rsh_guess, 100.0, 100000.0))
    rs_guess = float(np.clip(rs_guess, 0.01, 20.0))

    defaults = {
        "Jph": jsc,
        "J01": 1e-12,
        "J02": 1e-8,
        "n1": 1.0,
        "n2": 2.0,
        "Rs": rs_guess,
        "Rsh": rsh_guess,
    }
    bounds = {
        "Jph": (max(jsc * 0.75, 1e-9), max(jsc * 1.25, jsc + 1e-6)),
        "J01": (1e-20, 1e-5),
        "J02": (1e-15, 1e-3),
        "n1": (0.8, 1.3),
        "n2": (1.4, 3.0),
        "Rs": (0.01, max(20.0, rs_guess * 5)),
        "Rsh": (100.0, max(100000.0, rsh_guess * 5)),
    }
    meta = {"Jsc": jsc, "Voc": voc, "Rs_guess": rs_guess, "Rsh_guess": rsh_guess}
    return defaults, bounds, meta


def build_fit_inputs(V_data, J_data_mA, request_params, request_bounds):
    defaults, default_bounds, meta = estimate_defaults(V_data, J_data_mA)
    request_params = request_params or {}
    request_bounds = request_bounds or {}
    p0, b_min, b_max = [], [], []

    for name in PARAM_NAMES:
        lo, hi = default_bounds[name]
        item_bounds = request_bounds.get(name, {})
        try:
            lo = float(item_bounds.get("min", lo))
            hi = float(item_bounds.get("max", hi))
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

    return np.array(p0), np.array(b_min), np.array(b_max), meta


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


def raw_residuals(J_data_mA, J_model, use_log):
    if use_log:
        epsilon = 1e-6
        return np.log10(np.abs(J_model) + epsilon) - np.log10(np.abs(J_data_mA) + epsilon)
    scale = max(float(np.nanmax(np.abs(J_data_mA))), 1.0)
    return (J_model - J_data_mA) / scale


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/preview", methods=["POST"])
def preview():
    data = request.get_json(silent=True) or {}
    V_data, J_data_mA = parse_jv_csv(data.get("csv", ""))
    p0, _, _, meta = build_fit_inputs(V_data, J_data_mA, data.get("params"), data.get("bounds"))
    J_preview = double_diode_model(V_data, *p0)
    return jsonify({
        "success": True,
        "params": dict(zip(PARAM_NAMES, p0.tolist())),
        "V": V_data.tolist(),
        "J_exp": (-J_data_mA).tolist(),
        "J_fit": (-J_preview).tolist(),
        "rmse": rmse(J_data_mA, J_preview),
        "meta": meta,
    })


@app.route("/api/fit", methods=["POST"])
def fit():
    data = request.get_json(silent=True) or {}
    V_data, J_data_mA = parse_jv_csv(data.get("csv", ""))
    p0, b_min, b_max, meta = build_fit_inputs(
        V_data,
        J_data_mA,
        data.get("params"),
        data.get("bounds"),
    )

    fixed = data.get("fixed", {}) or {}
    options = data.get("options", {}) or {}
    fixed_flags = np.array([fixed.get(name, False) for name in PARAM_NAMES], dtype=bool)

    idx_free = np.where(~fixed_flags)[0]
    idx_fixed = np.where(fixed_flags)[0]

    if len(idx_free) == 0:
        J_final = double_diode_model(V_data, *p0)
        return jsonify({
            "success": True,
            "params": dict(zip(PARAM_NAMES, p0.tolist())),
            "V": V_data.tolist(),
            "J_exp": (-J_data_mA).tolist(),
            "J_fit": (-J_final).tolist(),
            "rmse": rmse(J_data_mA, J_final),
            "fixed": fixed,
            "meta": meta,
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

    use_global = bool(options.get("use_global", False))
    use_nelder = bool(options.get("use_nelder", False))
    use_log = bool(options.get("use_log", False))

    def residual_func(params_free):
        p_full = reconstruct_full_params(params_free)
        J_model = double_diode_model(V_data, *p_full)
        return raw_residuals(J_data_mA, J_model, use_log)

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
            strategy="best1bin",
            maxiter=35,
            popsize=8,
            workers=1,
            polish=False,
            updating="immediate",
        )
        final_params_free = result.x

    if use_nelder:
        res = minimize(
            cost_func,
            final_params_free,
            method="Nelder-Mead",
            tol=1e-5,
            options={"maxiter": 900, "xatol": 1e-5, "fatol": 1e-5},
        )
        final_params_free = np.clip(res.x, b_min_free, b_max_free)

    try:
        lsq = least_squares(
            residual_func,
            final_params_free,
            bounds=(b_min_free, b_max_free),
            loss="linear",
            max_nfev=2400,
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
                max_nfev=1600,
            )
            final_params_free = popt
        except Exception:
            pass

    final_params_full = reconstruct_full_params(final_params_free)
    J_final = double_diode_model(V_data, *final_params_full)
    return jsonify({
        "success": True,
        "params": dict(zip(PARAM_NAMES, final_params_full.tolist())),
        "V": V_data.tolist(),
        "J_exp": (-J_data_mA).tolist(),
        "J_fit": (-J_final).tolist(),
        "rmse": rmse(J_data_mA, J_final),
        "fixed": fixed,
        "meta": meta,
    })


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
