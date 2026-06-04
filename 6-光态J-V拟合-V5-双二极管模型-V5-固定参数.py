import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit, fsolve, differential_evolution, minimize
from scipy.constants import k as k_B, e as q_e
import sys
import ctypes
import threading

# Matplotlib
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

try:
    import sv_ttk
except ImportError:
    pass

# --- 1. 核心模型 (保持不变) ---
T = 300.0
Vt = (k_B * T) / q_e 

def double_diode_model(V_array, Jph, J01, J02, n1, n2, Rs, Rsh):
    """
    双二极管隐式模型 (DDM)
    """
    J_calc = []
    # 转换为 A/cm² 和 Ohm*cm²
    Jph_A = Jph * 1e-3
    J01_A = J01 * 1e-3
    J02_A = J02 * 1e-3
    
    if Rsh < 1e-2: Rsh = 1e-2
    
    current_guess = -Jph_A 

    for V in V_array:
        def equation_to_solve(J):
            V_internal = V - J * Rs
            
            def safe_exp(val):
                if val > 100: return 1e43
                if val < -100: return 0.0
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
        
    return np.array(J_calc) * 1e3 # 返回 mA/cm²


# --- 2. 应用程序类 ---

class JVFitterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("J-V 拟合 (V10 - 稳定修复版)")
        self.root.geometry("1200x850") # 稍微加宽以容纳锁定按钮

        self.V_data = None
        self.J_data_mA = None
        self.J_fit_mA = None
        self.filename = ""
        self.last_fitted_params = None 
        
        # 参数定义
        self.param_vars = {
            "Jph": (tk.StringVar(value='10'), tk.StringVar(value='30')),
            "J01": (tk.StringVar(value='1e-20'), tk.StringVar(value='1e-5')),
            "J02": (tk.StringVar(value='1e-15'), tk.StringVar(value='1e-3')),
            "n1":  (tk.StringVar(value='0.8'), tk.StringVar(value='1.4')),
            "n2":  (tk.StringVar(value='1.5'), tk.StringVar(value='3.0')),
            "Rs":  (tk.StringVar(value='0.01'), tk.StringVar(value='50')),
            "Rsh": (tk.StringVar(value='100'), tk.StringVar(value='100000'))
        }
        
        self.slider_vars = {k: tk.DoubleVar() for k in self.param_vars}
        self.preview_entry_vars = {k: tk.StringVar() for k in self.param_vars}
        self.slider_step_vars = {k: tk.StringVar(value='0.01') for k in self.param_vars}
        self.slider_step_vars['J01'].set('0.1')
        self.slider_step_vars['J02'].set('0.1')
        
        # [新增] 锁定状态变量
        self.fixed_vars = {k: tk.BooleanVar(value=False) for k in self.param_vars}
        
        self.sliders = {}
        
        # 选项
        self.use_global_opt = tk.BooleanVar(value=False)
        self.log_scale_fit = tk.BooleanVar(value=False)
        self.use_nelder_mead = tk.BooleanVar(value=True)
        
        # 进度
        self.progress_var = tk.DoubleVar(value=0)
        self.is_running = False

        self.setup_ui()

    def setup_ui(self):
        self.paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.left_frame = ttk.Frame(self.paned, width=480) # 加宽左侧
        self.left_frame.pack_propagate(False)
        self.paned.add(self.left_frame, weight=1)
        
        self.right_frame = ttk.Frame(self.paned)
        self.paned.add(self.right_frame, weight=2)
        
        # 滚动区域
        self.canvas_scroll = tk.Canvas(self.left_frame, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.left_frame, orient="vertical", command=self.canvas_scroll.yview)
        self.scroll_content = ttk.Frame(self.canvas_scroll)
        
        self.scroll_content.bind("<Configure>", lambda e: self.canvas_scroll.configure(scrollregion=self.canvas_scroll.bbox("all")))
        self.canvas_window = self.canvas_scroll.create_window((0, 0), window=self.scroll_content, anchor="nw")
        self.canvas_scroll.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas_scroll.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.left_frame.bind('<Configure>', lambda e: self.canvas_scroll.itemconfig(self.canvas_window, width=e.width))
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)

        self.status_lbl = ttk.Label(self.scroll_content, text="Ready", relief="sunken", anchor="w")
        self.status_lbl.pack(side="bottom", fill="x", pady=5)

        # 1. 导入
        f1 = ttk.LabelFrame(self.scroll_content, text="1. 导入数据")
        f1.pack(fill="x", padx=5, pady=5)
        ttk.Button(f1, text="打开 CSV", command=self.load_file).pack(fill="x", padx=5, pady=5)
        self.lbl_file = ttk.Label(f1, text="无文件", anchor="center")
        self.lbl_file.pack(fill="x", pady=2)

        # 2. 参数 (带锁定功能)
        f2 = ttk.LabelFrame(self.scroll_content, text="2. 参数设置 (勾选以锁定)")
        f2.pack(fill="x", padx=5, pady=5)
        
        grid = ttk.Frame(f2)
        grid.pack(fill="x", padx=5, pady=5)
        
        r = 0
        for k in self.param_vars:
            # Row A: Label, Slider, Fix Checkbox
            lbl_txt = k + " (log)" if "J0" in k else k
            ttk.Label(grid, text=lbl_txt).grid(row=r, column=0, sticky="w")
            
            s = ttk.Scale(grid, variable=self.slider_vars[k], orient="horizontal", command=lambda v, key=k: self.on_slider_move(v, key))
            s.bind("<ButtonRelease-1>", lambda e: self.preview_fit())
            s.grid(row=r, column=1, columnspan=4, sticky="ew", padx=(0, 5))
            self.sliders[k] = s
            
            # [新增] 锁定复选框
            chk_fix = ttk.Checkbutton(grid, text="锁定", variable=self.fixed_vars[k])
            chk_fix.grid(row=r, column=5, sticky="w")
            
            r+=1
            
            # Row B: Min, Max, Val
            ttk.Label(grid, text="Min:").grid(row=r, column=0, sticky="e")
            e_min = ttk.Entry(grid, textvariable=self.param_vars[k][0], width=7)
            e_min.grid(row=r, column=1, sticky="w")
            e_min.bind("<Return>", self.update_bounds_from_entry)
            
            ttk.Label(grid, text="Max:").grid(row=r, column=2, sticky="e")
            e_max = ttk.Entry(grid, textvariable=self.param_vars[k][1], width=7)
            e_max.grid(row=r, column=3, sticky="w")
            e_max.bind("<Return>", self.update_bounds_from_entry)
            
            ttk.Label(grid, text="Val:").grid(row=r, column=4, sticky="e")
            e_val = ttk.Entry(grid, textvariable=self.preview_entry_vars[k], width=7)
            e_val.grid(row=r, column=5, sticky="w")
            e_val.bind("<Return>", lambda e, key=k: self.on_entry_value_change(key))
            
            r+=1
            ttk.Separator(grid, orient="horizontal").grid(row=r, column=0, columnspan=6, sticky="ew", pady=2)
            r+=1

        # 3. 策略
        f3 = ttk.LabelFrame(self.scroll_content, text="3. 拟合策略")
        f3.pack(fill="x", padx=5, pady=5)
        
        ttk.Checkbutton(f3, text="启用全局优化 (DE)", variable=self.use_global_opt).pack(anchor="w", padx=10, pady=1)
        ttk.Checkbutton(f3, text="使用 Nelder-Mead (推荐)", variable=self.use_nelder_mead).pack(anchor="w", padx=10, pady=1)
        ttk.Checkbutton(f3, text="对数空间拟合 (Log-Space)", variable=self.log_scale_fit).pack(anchor="w", padx=10, pady=1)

        ttk.Label(f3, text="拟合进度:").pack(anchor="w", padx=10, pady=(5, 0))
        self.progressbar = ttk.Progressbar(f3, variable=self.progress_var, maximum=100)
        self.progressbar.pack(fill="x", padx=10, pady=5)

        self.btn_run = ttk.Button(f3, text="开始后台拟合", command=self.run_thread_fit, style="Accent.TButton")
        self.btn_run.pack(fill="x", padx=10, pady=10)

        # 4. 结果
        f4 = ttk.LabelFrame(self.scroll_content, text="4. 结果")
        f4.pack(fill="both", expand=True, padx=5, pady=5)
        self.txt_result = tk.Text(f4, height=10, width=30)
        self.txt_result.pack(fill="both", expand=True, padx=5, pady=5)
        
        btn_frame = ttk.Frame(f4)
        btn_frame.pack(fill="x", padx=5, pady=5)
        ttk.Button(btn_frame, text="导出参数", command=self.export_params).pack(side="left", expand=True)
        ttk.Button(btn_frame, text="导出CSV", command=self.export_data).pack(side="left", expand=True)

        self.fig = Figure(figsize=(5, 5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.right_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.init_plot()
        
        self.scroll_content.update_idletasks()
        self.canvas_scroll.configure(scrollregion=self.canvas_scroll.bbox("all"))

    # --- 基础功能 ---

    def init_plot(self):
        self.ax.clear()
        self.ax.set_title("J-V Curve Analysis")
        self.ax.set_xlabel("Voltage (V)")
        self.ax.set_ylabel("Current Density (mA/cm²)")
        self.ax.grid(True)
        self.canvas.draw()

    def load_file(self):
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if not path: return
        try:
            self.filename = path.split("/")[-1]
            self.lbl_file.config(text=self.filename)
            df = pd.read_csv(path)
            cols = [c.lower() for c in df.columns]
            v_idx = next(i for i, c in enumerate(cols) if "volt" in c or "v" == c.strip())
            j_idx = next(i for i, c in enumerate(cols) if "curr" in c or "j" == c.strip())
            self.V_data = df.iloc[:, v_idx].values
            self.J_data_mA = df.iloc[:, j_idx].values
            if np.mean(self.J_data_mA) > 0: self.J_data_mA = -self.J_data_mA
            self.estimate_initials()
            self.update_plot_data()
            self.status_lbl.config(text="数据加载完成")
        except Exception as e:
            messagebox.showerror("Error", f"读取失败: {e}")

    def estimate_initials(self):
        Jsc = -np.min(self.J_data_mA)
        defaults = {
            "Jph": (Jsc*0.9, Jsc*1.1, Jsc),
            "J01": (1e-20, 1e-5, 1e-12),
            "J02": (1e-15, 1e-3, 1e-8),
            "n1":  (0.8, 1.3, 1.0),
            "n2":  (1.4, 3.0, 2.0),
            "Rs":  (0.01, 20.0, 1.0),
            "Rsh": (100, 100000, 2000)
        }
        for k, (mn, mx, val) in defaults.items():
            self.param_vars[k][0].set(f"{mn:.2e}" if "J0" in k else f"{mn:.2f}")
            self.param_vars[k][1].set(f"{mx:.2e}" if "J0" in k else f"{mx:.2f}")
            if "J0" in k:
                self.sliders[k].configure(from_=np.log10(mn), to=np.log10(mx))
                self.slider_vars[k].set(np.log10(val))
                self.preview_entry_vars[k].set(f"{val:.2e}")
            else:
                self.sliders[k].configure(from_=mn, to=mx)
                self.slider_vars[k].set(val)
                self.preview_entry_vars[k].set(f"{val:.2f}")

    def on_slider_move(self, val, key):
        v = float(val)
        if "J0" in key: self.preview_entry_vars[key].set(f"{10**v:.2e}")
        else: self.preview_entry_vars[key].set(f"{v:.4f}")

    def update_bounds_from_entry(self, event=None):
        for k in self.param_vars:
            try:
                mn = float(self.param_vars[k][0].get())
                mx = float(self.param_vars[k][1].get())
                if "J0" in k:
                    if mn<=0: mn=1e-25
                    self.sliders[k].configure(from_=np.log10(mn), to=np.log10(mx))
                else: self.sliders[k].configure(from_=mn, to=mx)
            except: pass
        self.preview_fit()

    def on_entry_value_change(self, key):
        try:
            val = float(self.preview_entry_vars[key].get())
            if "J0" in key: self.slider_vars[key].set(np.log10(val))
            else: self.slider_vars[key].set(val)
            self.preview_fit()
        except: pass

    def get_current_params_and_bounds(self):
        p0, b_min, b_max = [], [], []
        for k in self.param_vars:
            val = self.slider_vars[k].get()
            if "J0" in k: val = 10**val
            p0.append(val)
            b_min.append(float(self.param_vars[k][0].get()))
            b_max.append(float(self.param_vars[k][1].get()))
        return np.array(p0), (b_min, b_max)

    def preview_fit(self):
        if self.V_data is None or self.is_running: return
        p, _ = self.get_current_params_and_bounds()
        try:
            self.J_fit_mA = double_diode_model(self.V_data, *p)
            self.update_plot_data()
            rmse = np.sqrt(np.mean((self.J_data_mA - self.J_fit_mA)**2))
            self.show_results(p, rmse, prefix="[预览]")
        except: pass

    # --- 核心：多线程拟合逻辑 (支持锁定参数) ---

    def run_thread_fit(self):
        if self.V_data is None: return
        
        p0, (b_min, b_max) = self.get_current_params_and_bounds()
        
        # [新增] 获取锁定状态
        fixed_flags = [self.fixed_vars[k].get() for k in self.param_vars]
        
        use_global = self.use_global_opt.get()
        use_nelder = self.use_nelder_mead.get()
        use_log = self.log_scale_fit.get()
        
        self.is_running = True
        self.btn_run.config(state="disabled", text="拟合中...请稍候")
        self.progress_var.set(0)
        self.status_lbl.config(text="初始化计算...")
        
        t = threading.Thread(
            target=self._fit_worker, 
            args=(p0, b_min, b_max, fixed_flags, use_global, use_nelder, use_log)
        )
        t.daemon = True
        t.start()

    def _fit_worker(self, p0, b_min, b_max, fixed_flags, use_global, use_nelder, use_log):
        try:
            # 转换为 numpy 数组方便索引
            p0 = np.array(p0)
            fixed_flags = np.array(fixed_flags, dtype=bool)
            b_min = np.array(b_min)
            b_max = np.array(b_max)
            
            # 区分自由参数和固定参数
            idx_free = np.where(~fixed_flags)[0]
            idx_fixed = np.where(fixed_flags)[0]
            
            # 如果全部被固定，直接计算结果
            if len(idx_free) == 0:
                self.root.after(0, lambda: self.status_lbl.config(text="全部参数已锁定，计算模拟值..."))
                J_final = double_diode_model(self.V_data, *p0)
                rmse = np.sqrt(np.mean((self.J_data_mA - J_final)**2))
                self.root.after(0, self.on_fit_complete, p0, J_final, rmse)
                return

            # 提取自由参数的初始值和边界
            p0_free = p0[idx_free]
            b_min_free = b_min[idx_free]
            b_max_free = b_max[idx_free]
            
            # 提取固定参数的值 (作为常量)
            vals_fixed = p0[idx_fixed]

            # 辅助函数：将自由参数重组为全参数
            def reconstruct_full_params(params_free):
                params_full = np.zeros_like(p0)
                params_full[idx_fixed] = vals_fixed
                params_full[idx_free] = params_free
                return params_full

            # 定义代价函数 (仅针对自由参数)
            def cost_func(params_free):
                # Nelder-Mead 边界惩罚
                if use_nelder:
                    for i, val in enumerate(params_free):
                        if val < b_min_free[i] or val > b_max_free[i]:
                            return 1e20 

                p_full = reconstruct_full_params(params_free)
                J_model = double_diode_model(self.V_data, *p_full)
                
                if use_log:
                    epsilon = 1e-6
                    log_exp = np.log10(np.abs(self.J_data_mA) + epsilon)
                    log_mod = np.log10(np.abs(J_model) + epsilon)
                    return np.sum((log_exp - log_mod)**2)
                else:
                    return np.sum((self.J_data_mA - J_model)**2)

            final_params_free = p0_free
            
            # --- 阶段 1: 全局优化 (仅优化自由参数) ---
            if use_global:
                de_bounds_free = list(zip(b_min_free, b_max_free))
                max_iter_global = 50
                iter_count_global = 0
                
                def de_callback(xk, convergence):
                    nonlocal iter_count_global
                    iter_count_global += 1
                    prog = (iter_count_global / max_iter_global) * 50
                    self.root.after(0, lambda: self.progress_var.set(prog))
                    self.root.after(0, lambda: self.status_lbl.config(text=f"全局优化 (降维): {iter_count_global}/{max_iter_global}"))
                
                # FIX: 显式设置 workers=1 以避免 pickling 局部函数错误
                result = differential_evolution(
                    cost_func, 
                    de_bounds_free, 
                    strategy='best1bin', 
                    maxiter=max_iter_global, 
                    popsize=10, 
                    callback=de_callback,
                    workers=1 # 关键修复
                )
                final_params_free = result.x

            # --- 阶段 2: 局部精修 (仅优化自由参数) ---
            start_prog = 50 if use_global else 0
            remain_prog = 100 - start_prog
            
            if use_nelder:
                iter_count_local = 0
                max_iter_est = 500
                
                def nm_callback(xk):
                    nonlocal iter_count_local
                    iter_count_local += 1
                    frac = min(iter_count_local / max_iter_est, 0.95)
                    prog = start_prog + frac * remain_prog
                    self.root.after(0, lambda: self.progress_var.set(prog))
                    self.root.after(0, lambda: self.status_lbl.config(text=f"局部精修 (Nelder-Mead): {iter_count_local}"))

                res = minimize(
                    cost_func, 
                    final_params_free, 
                    method='Nelder-Mead', 
                    callback=nm_callback,
                    tol=1e-5,
                    options={'maxiter': 2000}
                )
                final_params_free = res.x
            else:
                self.root.after(0, lambda: self.status_lbl.config(text="局部精修 (Least Squares)..."))
                # Curve fit 需要特殊的 wrapper
                def model_wrapper_for_curve_fit(v, *args_free):
                    # args_free 是 tuple, 需转 array
                    p_f = np.array(args_free)
                    p_all = reconstruct_full_params(p_f)
                    return double_diode_model(v, *p_all)

                try:
                    popt, _ = curve_fit(
                        model_wrapper_for_curve_fit,
                        self.V_data,
                        self.J_data_mA,
                        p0=final_params_free,
                        bounds=(b_min_free, b_max_free),
                        max_nfev=2000
                    )
                    final_params_free = popt
                except: pass

            # 重组最终参数
            final_params_full = reconstruct_full_params(final_params_free)
            J_final = double_diode_model(self.V_data, *final_params_full)
            rmse = np.sqrt(np.mean((self.J_data_mA - J_final)**2))
            
            self.root.after(0, self.on_fit_complete, final_params_full, J_final, rmse)

        except Exception as e:
            self.root.after(0, self.on_fit_error, str(e))

    def on_fit_complete(self, params, J_final, rmse):
        self.is_running = False
        self.btn_run.config(state="normal", text="开始后台拟合")
        self.progress_var.set(100)
        self.status_lbl.config(text="拟合完成！")
        
        self.last_fitted_params = params
        self.J_fit_mA = J_final
        
        # 更新UI
        for i, k in enumerate(self.param_vars):
            val = params[i]
            if "J0" in k:
                self.slider_vars[k].set(np.log10(val))
                self.preview_entry_vars[k].set(f"{val:.2e}")
            else:
                self.slider_vars[k].set(val)
                self.preview_entry_vars[k].set(f"{val:.4f}")
        
        self.update_plot_data()
        self.show_results(params, rmse, prefix="[最终结果]")
        messagebox.showinfo("完成", f"拟合成功！\nRMSE: {rmse:.5f}")

    def on_fit_error(self, err_msg):
        self.is_running = False
        self.btn_run.config(state="normal", text="开始后台拟合")
        self.status_lbl.config(text="拟合出错")
        messagebox.showerror("计算错误", f"线程中发生错误:\n{err_msg}")

    # --- 辅助 ---

    def update_plot_data(self):
        self.ax.clear()
        self.ax.plot(self.V_data, -self.J_data_mA, 'bo', markersize=3, alpha=0.5, label='Exp Data')
        if self.J_fit_mA is not None:
            self.ax.plot(self.V_data, -self.J_fit_mA, 'r-', linewidth=2, label='Fit Model')
            if self.log_scale_fit.get(): self.ax.set_yscale('log')
            else: self.ax.set_yscale('linear')
        self.ax.set_title("J-V Curve (Double Diode)")
        self.ax.set_xlabel("Voltage (V)")
        self.ax.set_ylabel("Current Density (mA/cm²)")
        self.ax.legend()
        self.ax.grid(True, which="both")
        self.canvas.draw()

    def show_results(self, p, rmse, prefix=""):
        txt = f"{prefix}\nRMSE: {rmse:.5f}\n"
        names = list(self.param_vars.keys())
        for i, val in enumerate(p):
            txt += f"{names[i]}: {val:.4e}"
            if self.fixed_vars[names[i]].get():
                txt += " [锁]"
            txt += "\n"
        self.txt_result.delete(1.0, tk.END)
        self.txt_result.insert(tk.END, txt)

    def export_params(self):
        if not self.last_fitted_params is not None: return
        f = filedialog.asksaveasfilename(defaultextension=".txt")
        if f:
            with open(f, "w") as file: file.write(self.txt_result.get(1.0, tk.END))

    def export_data(self):
        if self.J_fit_mA is None: return
        f = filedialog.asksaveasfilename(defaultextension=".csv")
        if f:
            pd.DataFrame({"V": self.V_data, "J_Exp": -self.J_data_mA, "J_Fit": -self.J_fit_mA}).to_csv(f, index=False)

    def _on_mousewheel(self, event):
        self.canvas_scroll.yview_scroll(int(-1*(event.delta/120)), "units")

if __name__ == "__main__":
    if sys.platform == "win32":
        try: ctypes.windll.user32.SetProcessDPIAware()
        except: pass
    root = tk.Tk()
    try: sv_ttk.set_theme("light")
    except: pass
    app = JVFitterApp(root)
    root.mainloop()