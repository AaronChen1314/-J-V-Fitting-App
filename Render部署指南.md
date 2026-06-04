# J-V曲线拟合应用 Render部署指南

## 前置准备

### 1. 确保项目文件完整
你的项目应包含以下关键文件：
- ✅ `app.py` - Flask应用主文件
- ✅ `requirements.txt` - Python依赖列表
- ✅ `render.yaml` - Render部署配置
- ✅ `templates/index.html` - 前端页面
- ✅ `static/` - 静态资源目录
- ✅ `.gitignore` - Git忽略配置

---

## 部署步骤

### 第一步：初始化Git仓库

在项目目录下打开终端，执行：

```powershell
cd "c:\Users\Q\Desktop\搭建个人静态网站-分步\9-光态曲线拟合-双二极管"

# 初始化Git仓库
git init

# 添加所有文件
git add .

# 提交
git commit -m "Initial commit: J-V curve fitting web app"
```

### 第二步：推送到GitHub

1. 在GitHub上创建新仓库（建议命名：`jv-fitting-app`）
2. 按GitHub提示添加远程仓库并推送：

```powershell
# 添加远程仓库（替换为你的用户名和仓库名）
git remote add origin https://github.com/[你的用户名]/[仓库名].git

# 推送到main分支
git branch -M main
git push -u origin main
```

### 第三步：在Render上部署

1. **访问Render网站**
   - 打开 https://render.com
   - 登录你的账号

2. **创建新Web Service**
   - 点击右上角 "New +" → "Web Service"
   - 选择你刚推送的GitHub仓库
   - 点击 "Connect"

3. **配置部署（render.yaml会自动加载）**
   
   Render会自动读取项目中的 `render.yaml` 配置，确认以下设置：
   - **Name**: `jv-fitting` (或自定义名称)
   - **Runtime**: `Python 3`
   - **Region**: 选择离你近的区域（如 Singapore）
   - **Branch**: `main`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 120 app:app`
   - **Plan**: 选择免费的 `Free` 计划

4. **部署**
   - 点击 "Create Web Service"
   - 等待约2-5分钟，Render会自动构建和部署

5. **访问应用**
   - 部署完成后，Render会提供一个URL，如：`https://jv-fitting.onrender.com`
   - 点击该URL即可访问你的应用！

---

## 验证部署

部署成功后，请验证以下功能：
- ✅ 页面正常加载
- ✅ CSV文件可导入
- ✅ J-V曲线正常显示
- ✅ 拟合功能可用
- ✅ 结果可导出

---

## 常见问题排查

### 问题1：构建失败
**检查**：
- `requirements.txt` 中的包版本是否兼容
- Python版本在render.yaml中是否正确设置（当前为3.11.0）

### 问题2：应用启动失败
**检查**：
- `gunicorn` 是否在requirements.txt中
- 启动命令是否正确指向 `app:app`

### 问题3：静态资源加载失败
**检查**：
- `templates/` 和 `static/` 目录是否被正确提交到Git
- `.gitignore` 是否误忽略了这些目录

---

## 项目文件清单（确保都已提交）

```
9-光态曲线拟合-双二极管/
├── app.py
├── requirements.txt
├── render.yaml
├── .gitignore
├── templates/
│   └── index.html
├── static/
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── main.js
└── [其他文件...]
```

---

## 部署配置说明（render.yaml）

```yaml
services:
  - type: web              # 服务类型：Web服务
    name: jv-fitting       # 服务名称
    runtime: python        # 运行时：Python
    buildCommand: pip install -r requirements.txt    # 构建命令
    startCommand: gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 120 app:app
    envVars:
      - key: PYTHON_VERSION
        value: 3.11.0     # Python版本
```

---

## 更新已部署的应用

后续代码更新只需：

```powershell
# 1. 提交修改
git add .
git commit -m "描述你的修改"

# 2. 推送到GitHub
git push origin main
```

Render会自动检测到GitHub推送并重新部署！

---

## 技术支持

如遇问题：
1. 查看Render控制台的 "Logs" 标签页
2. 检查应用是否有错误日志
3. 参考Render官方文档：https://render.com/docs

---

部署完成时间：2026-06-04
