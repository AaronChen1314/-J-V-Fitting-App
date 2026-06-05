from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
import io
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
from scipy.constants import e as q_e, k as k_B
from scipy.optimize import differential_evolution, fsolve, least_squares, minimize

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

T = 300.0
Vt = (k_B * T) / q_e

PARAM_NAMES = ["Jph", "J01", "J02", "n1", "n2", "Rs", "Rsh"]
LOG_PARAMS = {"J01", "J02"}
BASE_DIR = Path(__file__).resolve().parent
SAMPLE_FILES = {
    "nbg": BASE_DIR / "钙钙" / "0-1-nbg真实.csv",
    "wbg": BASE_DIR / "钙钙" / "0-1-wbg-真实.csv",
}


@app.errorhandler(Exception)
def handle_exception(error):
    if request.path.startswith("/api/"):
        if isinstance(error, RequestEntityTooLarge):
            return jsonify({"success": False, "error": "请求内容超过 2 MB 限制。"}), 413
        if isinstance(error, ValueError):
            return jsonify({"success": False, "error": str(error)}), 400
        if isinstance(error, HTTPException):
            return jsonify({"success": False, "error": error.description}), error.code
        app.logger.exception("Unhandled API error")
        return jsonify({"success": False, "error": "服务器处理请求失败。"}), 500
    raise error


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


def double_diode_model(V_array, Jph, J01, J02, n1, n2, Rs, Rsh, return_diagnostics=False):
    J_calc = []
    converged = []
    residuals = []
    Jph_A = float(Jph) * 1e-3
    J01_A = float(J01) * 1e-3
    J02_A = float(J02) * 1e-3
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
                solution, info, ier, _ = fsolve(
                    equation_to_solve, current_guess, xtol=1e-8, maxfev=80, full_output=True
                )
            J_solution = float(solution[0])
            residual = abs(float(np.asarray(equation_to_solve(J_solution)).item()))
            is_converged = bool(ier == 1 and np.isfinite(J_solution) and residual <= 1e-7)
            if not is_converged:
                J_solution = current_guess
        except Exception:
            J_solution = current_guess
            residual = float("inf")
            is_converged = False
        current_guess = J_solution
        J_calc.append(J_solution)
        converged.append(is_converged)
        residuals.append(residual)

    model = np.array(J_calc) * 1e3
    if not return_diagnostics:
        return model
    finite_residuals = [value for value in residuals if np.isfinite(value)]
    diagnostics = {
        "points": len(J_calc),
        "converged_points": int(np.count_nonzero(converged)),
        "failed_points": int(len(J_calc) - np.count_nonzero(converged)),
        "max_equation_residual": max(finite_residuals, default=None),
        "converged_mask": np.asarray(converged, dtype=bool),
    }
    return model, diagnostics


def parse_jv_csv(csv_content):
    if not isinstance(csv_content, str) or not csv_content.strip():
        raise ValueError("CSV 内容为空。")
    if len(csv_content.encode("utf-8")) > 1_500_000:
        raise ValueError("CSV 内容超过 1.5 MB 限制。")

    try:
        df = pd.read_csv(io.StringIO(csv_content))
    except Exception as error:
        raise ValueError("CSV 无法解析，请检查分隔符和文件编码。") from error
    if df.shape[1] < 2:
        raise ValueError("CSV 至少需要电压和电流两列。")

    cols = [str(c).strip().lower() for c in df.columns]
    v_candidates = [i for i, c in enumerate(cols) if "volt" in c or c == "v"]
    j_candidates = [
        i
        for i, c in enumerate(cols)
        if "curr" in c or c in {"j", "current", "current density"}
    ]
    v_idx = v_candidates[0] if v_candidates else 0
    j_idx = j_candidates[0] if j_candidates else (1 if v_idx == 0 else 0)

    V_data = pd.to_numeric(df.iloc[:, v_idx], errors="coerce").to_numpy()
    J_data_mA = pd.to_numeric(df.iloc[:, j_idx], errors="coerce").to_numpy()
    mask = np.isfinite(V_data) & np.isfinite(J_data_mA)
    V_data = V_data[mask]
    J_data_mA = J_data_mA[mask]
    if len(V_data) < 3:
        raise ValueError("至少需要 3 个有效的 V-J 数据点。")

    order = np.argsort(V_data)
    V_data = V_data[order]
    J_data_mA = J_data_mA[order]
    if len(np.unique(V_data)) < len(V_data):
        grouped = pd.DataFrame({"V": V_data, "J": J_data_mA}).groupby("V", as_index=False).mean()
        V_data = grouped["V"].to_numpy()
        J_data_mA = grouped["J"].to_numpy()
    if len(V_data) < 3:
        raise ValueError("合并重复电压后，至少需要 3 个不同电压点。")

    # Internal convention follows the original V5 script: illuminated current is negative.
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
        j0 = float(np.median(J[near])) if np.any(near) else float(J[np.argmin(np.abs(V))])
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
        "n1": (0.8, 1.4),
        "n2": (1.2, 3.5),
        "Rs": (0.001, max(30.0, rs_guess * 10)),
        "Rsh": (10.0, max(200000.0, rsh_guess * 10)),
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
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} 的参数边界不是有效数字。") from error

        if name in LOG_PARAMS:
            lo = max(lo, 1e-30)
        if not np.isfinite(lo) or not np.isfinite(hi):
            raise ValueError(f"{name} 的参数边界必须是有限数字。")
        if hi <= lo:
            raise ValueError(f"{name} 的最大值必须大于最小值。")

        try:
            val = float(request_params.get(name, defaults[name]))
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} 的初始值不是有效数字。") from error
        if not np.isfinite(val):
            raise ValueError(f"{name} 的初始值必须是有限数字。")
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


def finite_float(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


def get_pin(options):
    pin = finite_float((options or {}).get("pin"))
    if pin is None or pin <= 0:
        return 100.0
    return float(np.clip(pin, 1e-9, 1e6))


def calculate_power_metrics(params, jsc, voc, pin=100.0, points=1000):
    jsc = finite_float(jsc)
    voc = finite_float(voc)
    pin = get_pin({"pin": pin})
    if params is None or jsc is None or voc is None or jsc <= 0 or voc <= 0:
        return {
            "Vmp": None,
            "Jmp": None,
            "Pmax": None,
            "Pin": pin,
            "PCE": None,
            "FF": None,
        }

    sample_count = bounded_int(points, 1000, 50, 5000)
    V_dense = np.linspace(0.0, voc, sample_count)
    J_dense = -double_diode_model(V_dense, *params)
    power = V_dense * J_dense
    valid = np.isfinite(V_dense) & np.isfinite(J_dense) & np.isfinite(power)
    valid &= (V_dense >= 0) & (J_dense >= 0)
    if not np.any(valid):
        return {
            "Vmp": None,
            "Jmp": None,
            "Pmax": None,
            "Pin": pin,
            "PCE": None,
            "FF": None,
        }

    valid_indices = np.where(valid)[0]
    best_index = int(valid_indices[np.argmax(power[valid])])
    pmax = max(float(power[best_index]), 0.0)
    ff = pmax / (voc * jsc) * 100.0 if voc > 0 and jsc > 0 else None
    return {
        "Vmp": float(V_dense[best_index]),
        "Jmp": float(J_dense[best_index]),
        "Pmax": pmax,
        "Pin": pin,
        "PCE": pmax / pin * 100.0 if pin > 0 else None,
        "FF": ff if ff is not None and np.isfinite(ff) else None,
    }


def residual_diagnostics(J_data_mA, J_model):
    residuals = np.asarray(J_model, dtype=float) - np.asarray(J_data_mA, dtype=float)
    finite = residuals[np.isfinite(residuals)]
    if finite.size == 0:
        return {"mean": None, "mae": None, "max_abs": None, "std": None}
    return {
        "mean": float(np.mean(finite)),
        "mae": float(np.mean(np.abs(finite))),
        "max_abs": float(np.max(np.abs(finite))),
        "std": float(np.std(finite)),
    }


def residual_values(J_data_mA, J_model, use_log):
    if use_log:
        epsilon = 1e-6
        signed_log = lambda values: np.sign(values) * np.log10(1.0 + np.abs(values) / epsilon)
        return signed_log(J_model) - signed_log(J_data_mA)
    scale = max(float(np.nanmax(np.abs(J_data_mA))), 1.0)
    return (J_model - J_data_mA) / scale


def candidate_scores(J_data_mA, J_model):
    raw_rmse = rmse(J_data_mA, J_model)
    current_scale = max(float(np.sqrt(np.mean(J_data_mA ** 2))), 1.0)
    log_residuals = residual_values(J_data_mA, J_model, True)
    log_rmse = float(np.sqrt(np.mean(log_residuals ** 2)))
    data_log_scale = max(
        float(np.sqrt(np.mean(residual_values(np.zeros_like(J_data_mA), J_data_mA, True) ** 2))),
        1.0,
    )
    normalized_rmse = raw_rmse / current_scale
    balanced_score = normalized_rmse + 0.15 * (log_rmse / data_log_scale)
    return {
        "rmse": raw_rmse,
        "normalized_rmse": normalized_rmse,
        "log_rmse": log_rmse,
        "balanced_score": balanced_score,
    }


def fit_double_diode(V_data, J_data_mA, params=None, bounds=None, fixed=None, options=None):
    p0, b_min, b_max, meta = build_fit_inputs(V_data, J_data_mA, params, bounds)
    fixed = fixed or {}
    options = options or {}
    fixed_flags = np.array([fixed.get(name, False) for name in PARAM_NAMES], dtype=bool)

    idx_free = np.where(~fixed_flags)[0]
    idx_fixed = np.where(fixed_flags)[0]
    if len(idx_free) == 0:
        J_final, solver = double_diode_model(V_data, *p0, return_diagnostics=True)
        optimizer = {"success": True, "message": "全部参数已锁定。", "evaluations": 0}
        scores = candidate_scores(J_data_mA, J_final)
        candidate = candidate_summary("locked", scores, solver, optimizer, ["锁定参数"])
        diagnostics = build_diagnostics(p0, b_min, b_max, solver, optimizer, options)
        diagnostics.update({
            "mode": "锁定参数",
            "stages": ["锁定参数"],
            "selection_metric": normalize_selection_metric(options.get("selection_metric")),
            "selected_candidate": candidate["name"],
            "candidates": [candidate],
        })
        return p0, J_final, rmse(J_data_mA, J_final), {**meta, **diagnostics}

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
    selection_metric = normalize_selection_metric(options.get("selection_metric"))

    def residual_func(params_free, use_log_residual=False):
        p_full = reconstruct_full_params(params_free)
        J_model, solver = double_diode_model(V_data, *p_full, return_diagnostics=True)
        residuals = residual_values(J_data_mA, J_model, use_log_residual)
        if solver["failed_points"]:
            residuals = residuals + np.where(solver["converged_mask"], 0.0, 10.0)
        return residuals

    def cost_func(params_free, use_log_residual=False):
        if np.any(params_free < b_min_free) or np.any(params_free > b_max_free):
            return 1e20
        residuals = residual_func(params_free, use_log_residual)
        return float(np.sum(residuals ** 2))

    candidates = []

    def add_candidate(name, params_free, optimizer, stages):
        params_free = np.clip(np.asarray(params_free, dtype=float), b_min_free, b_max_free)
        params_full = reconstruct_full_params(params_free)
        model, solver = double_diode_model(V_data, *params_full, return_diagnostics=True)
        scores = candidate_scores(J_data_mA, model)
        candidates.append({
            "name": name,
            "params_free": params_free,
            "params": params_full,
            "model": model,
            "solver": solver,
            "optimizer": optimizer,
            "stages": stages,
            "scores": scores,
        })
        return candidates[-1]

    def run_lsq(name, start, use_log_residual, stages):
        result = least_squares(
            lambda values: residual_func(values, use_log_residual),
            np.clip(start, b_min_free, b_max_free),
            bounds=(b_min_free, b_max_free),
            loss="linear",
            max_nfev=bounded_int(
                options.get("log_max_nfev" if use_log_residual else "max_nfev"),
                300 if use_log_residual else 2400,
                20,
                5000,
            ),
            xtol=1e-9,
            ftol=1e-9,
            gtol=1e-9,
        )
        optimizer = {
            "success": bool(result.success),
            "message": str(result.message),
            "evaluations": int(result.nfev),
            "cost": float(result.cost),
        }
        return add_candidate(name, result.x, optimizer, stages)

    add_candidate(
        "initial",
        p0_free,
        {"success": True, "message": "初始参数候选。", "evaluations": 0},
        ["初始参数"],
    )
    linear_candidate = run_lsq("linear_lsq", p0_free, False, ["线性最小二乘"])

    if use_global:
        result = differential_evolution(
            lambda values: cost_func(values, False),
            list(zip(b_min_free, b_max_free)),
            strategy="best1bin",
            maxiter=bounded_int(options.get("global_maxiter"), 35, 1, 100),
            popsize=bounded_int(options.get("global_popsize"), 8, 3, 20),
            workers=1,
            polish=False,
            updating="immediate",
        )
        global_candidate = add_candidate(
            "global",
            result.x,
            {
                "success": bool(result.success),
                "message": str(result.message),
                "evaluations": int(result.nfev),
                "cost": float(result.fun),
            },
            ["差分进化"],
        )
        run_lsq("global_linear_lsq", global_candidate["params_free"], False, ["差分进化", "线性最小二乘"])

    if use_nelder:
        best_rmse_candidate = min(candidates, key=lambda item: item["scores"]["rmse"])
        res = minimize(
            lambda values: cost_func(values, False),
            best_rmse_candidate["params_free"],
            method="Nelder-Mead",
            tol=1e-5,
            options={
                "maxiter": bounded_int(options.get("nelder_maxiter"), 900, 10, 3000),
                "xatol": 1e-5,
                "fatol": 1e-5,
            },
        )
        nelder_candidate = add_candidate(
            "nelder_mead",
            res.x,
            {
                "success": bool(res.success),
                "message": str(res.message),
                "evaluations": int(res.nfev),
                "cost": float(res.fun),
            },
            best_rmse_candidate["stages"] + ["Nelder-Mead"],
        )
        run_lsq(
            "nelder_linear_lsq",
            nelder_candidate["params_free"],
            False,
            nelder_candidate["stages"] + ["线性最小二乘"],
        )

    if use_log:
        run_lsq("low_current_lsq", p0_free, True, ["低电流候选"])
        run_lsq(
            "best_linear_low_current_lsq",
            linear_candidate["params_free"],
            True,
            ["线性最小二乘", "低电流候选"],
        )

    selected = select_candidate(candidates, selection_metric)
    diagnostics = build_diagnostics(
        selected["params"], b_min, b_max, selected["solver"], selected["optimizer"], options
    )
    diagnostics.update({
        "mode": "整体 RMSE 择优" if selection_metric == "rmse" else "低电流优先择优",
        "stages": selected["stages"],
        "selection_metric": selection_metric,
        "selected_candidate": selected["name"],
        "candidates": [
            candidate_summary(
                item["name"], item["scores"], item["solver"], item["optimizer"], item["stages"]
            )
            for item in candidates
        ],
    })
    return selected["params"], selected["model"], selected["scores"]["rmse"], {**meta, **diagnostics}


def normalize_selection_metric(value):
    return "balanced" if value == "balanced" else "rmse"


def select_candidate(candidates, selection_metric):
    score_key = "rmse" if normalize_selection_metric(selection_metric) == "rmse" else "balanced_score"
    return min(candidates, key=lambda item: (item["scores"][score_key], item["scores"]["rmse"]))


def candidate_summary(name, scores, solver, optimizer, stages):
    return {
        "name": name,
        "rmse": scores["rmse"],
        "normalized_rmse": scores["normalized_rmse"],
        "log_rmse": scores["log_rmse"],
        "balanced_score": scores["balanced_score"],
        "failed_points": solver["failed_points"],
        "optimizer_success": bool(optimizer.get("success", False)),
        "stages": stages,
    }


def bounded_int(value, default, minimum, maximum):
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return int(np.clip(parsed, minimum, maximum))


def build_diagnostics(params, b_min, b_max, solver, optimizer, options):
    boundary_hits = []
    for name, value, lower, upper in zip(PARAM_NAMES, params, b_min, b_max):
        if name in LOG_PARAMS:
            value, lower, upper = np.log10([max(value, 1e-30), max(lower, 1e-30), max(upper, 1e-30)])
        span = max(upper - lower, 1e-30)
        if abs(value - lower) <= span * 1e-4 or abs(value - upper) <= span * 1e-4:
            boundary_hits.append(name)
    warnings_list = []
    if solver["failed_points"]:
        warnings_list.append(f"{solver['failed_points']} 个电压点的电流方程未可靠收敛。")
    if boundary_hits:
        warnings_list.append("以下参数触及边界：" + ", ".join(boundary_hits))
    if not optimizer.get("success", False):
        warnings_list.append("优化器未报告收敛，请谨慎使用结果。")
    mode = "对数残差" if options.get("use_log") else "线性残差"
    stages = ["最小二乘"]
    if options.get("use_global"):
        stages.insert(0, "差分进化")
    if options.get("use_nelder"):
        stages.insert(-1, "Nelder-Mead")
    return {
        "mode": mode,
        "stages": stages,
        "quality": "warning" if warnings_list else "good",
        "warnings": warnings_list,
        "boundary_hits": boundary_hits,
        "solver": {key: value for key, value in solver.items() if key != "converged_mask"},
        "optimizer": optimizer,
    }


def get_json_payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("请求正文必须是 JSON 对象。")
    return data


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/samples", methods=["GET"])
def samples():
    return jsonify({
        "success": True,
        "samples": [
            {"id": "nbg", "name": "NBG sample"},
            {"id": "wbg", "name": "WBG sample"},
        ],
    })


@app.route("/api/sample/<sample_id>", methods=["GET"])
def sample(sample_id):
    path = SAMPLE_FILES.get(sample_id)
    if path is None or not path.exists():
        raise ValueError("Unknown sample dataset.")
    return jsonify({
        "success": True,
        "id": sample_id,
        "name": "NBG sample" if sample_id == "nbg" else "WBG sample",
        "csv": path.read_text(encoding="utf-8-sig"),
    })


@app.route("/api/preview", methods=["POST"])
def preview():
    data = get_json_payload()
    V_data, J_data_mA = parse_jv_csv(data.get("csv", ""))
    p0, b_min, b_max, meta = build_fit_inputs(V_data, J_data_mA, data.get("params"), data.get("bounds"))
    J_preview, solver = double_diode_model(V_data, *p0, return_diagnostics=True)
    options = data.get("options") or {}
    meta.update({
        "power": calculate_power_metrics(p0, meta.get("Jsc"), meta.get("Voc"), get_pin(options)),
        "residuals": residual_diagnostics(J_data_mA, J_preview),
    })
    diagnostics = build_diagnostics(
        p0, b_min, b_max, solver, {"success": True, "message": "Preview only."}, {}
    )
    return jsonify({
        "success": True,
        "params": dict(zip(PARAM_NAMES, p0.tolist())),
        "V": V_data.tolist(),
        "J_exp": (-J_data_mA).tolist(),
        "J_fit": (-J_preview).tolist(),
        "rmse": rmse(J_data_mA, J_preview),
        "meta": {**meta, **diagnostics, "mode": "preview", "stages": ["preview"]},
    })


@app.route("/api/fit", methods=["POST"])
def fit():
    data = get_json_payload()
    V_data, J_data_mA = parse_jv_csv(data.get("csv", ""))
    options = data.get("options") or {}
    params, J_final, fit_rmse, meta = fit_double_diode(
        V_data,
        J_data_mA,
        params=data.get("params"),
        bounds=data.get("bounds"),
        fixed=data.get("fixed"),
        options=options,
    )
    meta.update({
        "power": calculate_power_metrics(params, meta.get("Jsc"), meta.get("Voc"), get_pin(options)),
        "residuals": residual_diagnostics(J_data_mA, J_final),
    })
    return jsonify({
        "success": True,
        "params": dict(zip(PARAM_NAMES, params.tolist())),
        "V": V_data.tolist(),
        "J_exp": (-J_data_mA).tolist(),
        "J_fit": (-J_final).tolist(),
        "rmse": fit_rmse,
        "fixed": data.get("fixed", {}) or {},
        "meta": meta,
    })


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
