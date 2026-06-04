# J-V 曲线拟合 - 双二极管模型

这是一个用于太阳电池 J-V 曲线拟合的 Web 应用，采用双二极管模型（Double Diode Model）。

## 功能特性

- 📊 导入 CSV 数据文件
- 🎛️ 可调参数设置（支持参数锁定）
- 🔧 SciPy 权威拟合引擎（差分进化、Nelder-Mead、最小二乘）
- 📈 实时图表可视化
- ✅ 求解收敛、参数触界与优化状态诊断
- 💾 结果导出（完整诊断 JSON 和 CSV）

## 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 运行应用
python app.py
```

访问 http://localhost:5000

## 测试

```bash
python -m unittest discover -s tests -v
```

## CSV 格式

CSV 文件应包含两列：电压（V）和电流密度（J），例如：

```
Voltage,Current
0.0,35.0
0.1,34.8
0.2,34.5
...
```

## 部署到 Render

1. 将代码推送到 GitHub 仓库
2. 在 Render 上创建新的 Web Service
3. 连接到你的 GitHub 仓库
4. 等待部署完成

## 参数说明

- **Jph**: 光生电流密度
- **J01, J02**: 反向饱和电流密度
- **n1, n2**: 二极管理想因子
- **Rs**: 串联电阻
- **Rsh**: 并联电阻
