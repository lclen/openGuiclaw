# Bootstrap 启动引导系统

## 概述

Bootstrap 模块负责程序启动前的环境初始化，包括依赖检查、目录创建、配置文件准备和 Node.js 环境设置。它确保程序在任何环境下都能正常运行。

## 架构

```
Bootstrap
├── 环境变量设置（APP_BASE_DIR）
├── Node.js 环境配置（便携版 + 隔离 npm）
├── 目录初始化（data/ 子目录）
├── 配置文件准备（config.json）
├── Python 依赖检查（requirements.txt）
└── npm 全局包检查（npm-requirements.txt）
```

## 核心功能

### 1. 应用基础目录

```python
def get_app_base_dir() -> Path:
    """
    返回程序的"家目录"：
    - frozen（PyInstaller）：exe 所在目录
    - 开发模式：项目根目录
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent
```

### 2. Node.js 环境设置

```python
def setup_node_env() -> None:
    """
    1. 将内置 Node.js 路径前推至 PATH 顶部
    2. 设置 npm global 目录为用户隔离路径
    """
    # 便携版 Node.js
    node_bin = app_base / "bin-node"
    os.environ["PATH"] = f"{node_bin}{os.pathsep}{os.environ['PATH']}"
    
    # 隔离 npm 全局包（避免 UAC 拦截）
    npm_global = Path("~/.openguiclaw/npm-global").expanduser()
    os.environ["NPM_CONFIG_PREFIX"] = str(npm_global)
    os.environ["PATH"] = f"{npm_global}{os.pathsep}{os.environ['PATH']}"
```

### 3. 目录初始化

```python
_REQUIRED_DATA_DIRS = [
    "data",
    "data/sessions",
    "data/memory",
    "data/diary",
    "data/journals",
    "data/identities",
    "data/identity",
    "data/plans",
    "data/scheduler",
    "data/screenshots",
    "data/consolidation",
]

def ensure_data_dirs() -> None:
    """创建所有必要的 data 子目录"""
    base = get_app_base_dir()
    for rel in _REQUIRED_DATA_DIRS:
        (base / rel).mkdir(parents=True, exist_ok=True)
```

### 4. 配置文件准备

```python
def ensure_config() -> None:
    """config.json 不存在时，从 config.json.example 自动复制"""
    config = base / "config.json"
    if config.exists():
        return
    
    example = base / "config.json.example"
    if example.exists():
        shutil.copy2(example, config)
        print("[Bootstrap] [OK] 已创建 config.json")
```

### 5. Python 依赖检查

```python
def check_python_deps(requirements_file: str = "requirements.txt") -> None:
    """安装 Python 依赖"""
    pip_python = sys.executable
    
    # 尝试使用 venv python
    venv_python = _get_venv_python()
    if venv_python:
        pip_python = venv_python
    
    result = subprocess.run([
        pip_python, "-m", "pip", "install",
        "-r", str(req_path),
        "-i", "https://mirrors.aliyun.com/pypi/simple/",
        "--quiet"
    ], ...)
```

### 6. npm 全局包检查

```python
def check_npm_deps(npm_requirements_file: str = "npm-requirements.txt") -> None:
    """安装 npm 全局包"""
    packages = parse_requirements(npm_requirements_file)
    
    for pkg in packages:
        pkg_name = _parse_pkg_name(pkg)
        if not _is_npm_pkg_installed(pkg_name, npm_global_prefix):
            subprocess.run([
                "npm", "install", "-g", pkg,
                "--registry=https://registry.npmmirror.com"
            ], ...)
```

### 7. 环境诊断

```python
def print_environment_diagnostics() -> None:
    """输出环境信息，供故障排查"""
    print("=" * 50)
    print("[环境诊断] OpenGuiclaw 启动预检")
    print(f" - [Python] {sys.executable}")
    print(f" - [App Base] {os.environ.get('APP_BASE_DIR')}")
    print(f" - [Node.js] {shutil.which('node')}")
    print(f" - [npm] {shutil.which('npm')}")
    print(f" - [沙盒隔离] {os.environ.get('NPM_CONFIG_PREFIX')}")
    print("=" * 50)
```

## API 接口

### 主入口

```python
from core.bootstrap import run

# 执行全部初始化
run()

# 跳过特定步骤
run(skip_python=True)   # 跳过 Python 依赖
run(skip_npm=True)      # 跳过 npm 依赖
```

### 单独调用

```python
from core.bootstrap import (
    get_app_base_dir,
    setup_node_env,
    ensure_data_dirs,
    ensure_config,
    check_python_deps,
    check_npm_deps,
    print_environment_diagnostics
)

# 获取应用目录
app_dir = get_app_base_dir()

# 设置 Node.js 环境
setup_node_env()

# 创建目录
ensure_data_dirs()

# 准备配置
ensure_config()

# 检查依赖
check_python_deps()
check_npm_deps()

# 诊断环境
print_environment_diagnostics()
```

## 配置

### requirements.txt

```txt
fastapi>=0.104.0
uvicorn>=0.24.0
openai>=1.0.0
httpx>=0.25.0
pydantic>=2.0.0
jinja2>=3.1.0
sse-starlette>=1.6.0
pyautogui>=0.9.54
mss>=9.0.0
pillow>=10.0.0
pyperclip>=1.8.2
numpy>=1.24.0
mcp>=1.0.0
```

### npm-requirements.txt

```txt
@pixiv/three-vrm@2.1.0
agent-browser@0.16.3
```

### 环境变量

```bash
# 应用基础目录
APP_BASE_DIR=D:\openGuiclaw

# npm 全局包路径
NPM_CONFIG_PREFIX=C:\Users\用户名\.openguiclaw\npm-global

# PATH（自动设置）
PATH=D:\openGuiclaw\bin-node;C:\Users\用户名\.openguiclaw\npm-global;...
```

## 最佳实践

### 1. 启动时调用

```python
# main.py
from core.bootstrap import run

if __name__ == "__main__":
    # 第一件事：初始化环境
    run()
    
    # 然后启动应用
    from core.agent import Agent
    agent = Agent()
    agent.run()
```

### 2. 防重复执行

```python
# Bootstrap 内置防重复机制
_already_run = False

def run(...):
    global _already_run
    if _already_run:
        return
    _already_run = True
    # 执行初始化...
```

### 3. 错误处理

```python
try:
    run()
except Exception as e:
    print(f"[Bootstrap] 初始化失败: {e}")
    print("请检查网络连接和权限设置")
    sys.exit(1)
```

### 4. 开发模式跳过

```python
# 开发时跳过依赖检查（加快启动）
if os.environ.get("DEV_MODE"):
    run(skip_python=True, skip_npm=True)
else:
    run()
```

### 5. 日志记录

```python
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bootstrap")

def run(...):
    logger.info("开始初始化...")
    setup_node_env()
    logger.info("Node.js 环境已设置")
    ensure_data_dirs()
    logger.info("目录已创建")
    # ...
```

## 故障排查

### 问题 1: Node.js 未找到

**症状**：`shutil.which("node")` 返回 None

**解决方案**：
```python
# 检查 bin-node 目录
node_bin = get_app_base_dir() / "bin-node"
print(f"Node.js 目录: {node_bin}")
print(f"是否存在: {node_bin.exists()}")

# 检查 PATH
print(f"PATH: {os.environ['PATH']}")

# 手动设置
os.environ["PATH"] = f"{node_bin}{os.pathsep}{os.environ['PATH']}"
```

### 问题 2: npm 安装失败

**症状**：`npm install -g` 报错

**解决方案**：
```python
# 检查 npm 配置
print(f"NPM_CONFIG_PREFIX: {os.environ.get('NPM_CONFIG_PREFIX')}")

# 检查网络
subprocess.run(["npm", "config", "get", "registry"])

# 切换镜像
subprocess.run([
    "npm", "config", "set", "registry",
    "https://registry.npmmirror.com"
])
```

### 问题 3: pip 安装失败

**症状**：`pip install` 报错

**解决方案**：
```python
# 检查 Python 路径
print(f"Python: {sys.executable}")

# 检查 pip
subprocess.run([sys.executable, "-m", "pip", "--version"])

# 升级 pip
subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])

# 切换镜像
subprocess.run([
    sys.executable, "-m", "pip", "install",
    "-r", "requirements.txt",
    "-i", "https://mirrors.aliyun.com/pypi/simple/"
])
```

### 问题 4: 权限不足

**症状**：创建目录或文件失败

**解决方案**：
```python
# 检查权限
import os
print(f"当前用户: {os.getlogin()}")
print(f"工作目录: {os.getcwd()}")

# 使用用户目录
user_dir = Path.home() / ".openguiclaw"
user_dir.mkdir(parents=True, exist_ok=True)
```

### 问题 5: frozen 模式路径错误

**症状**：PyInstaller 打包后找不到文件

**解决方案**：
```python
# 检查 _MEIPASS
if getattr(sys, "frozen", False):
    print(f"_MEIPASS: {sys._MEIPASS}")
    print(f"executable: {sys.executable}")
    
    # 资源文件在 _MEIPASS
    resource = Path(sys._MEIPASS) / "config.json.example"
    
    # 可写文件在 exe 旁边
    config = Path(sys.executable).parent / "config.json"
```

## 性能优化

### 1. 并行检查

```python
import concurrent.futures

def run_parallel():
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(check_python_deps),
            executor.submit(check_npm_deps)
        ]
        concurrent.futures.wait(futures)
```

### 2. 缓存检查结果

```python
_deps_checked = False

def check_python_deps():
    global _deps_checked
    if _deps_checked:
        return
    # 执行检查...
    _deps_checked = True
```

### 3. 跳过已安装

```python
# npm 包检查时跳过已安装
def _is_npm_pkg_installed(pkg_name: str, prefix: str) -> bool:
    node_modules = Path(prefix) / "node_modules"
    if pkg_name.startswith("@"):
        scope, name = pkg_name[1:].split("/", 1)
        return (node_modules / f"@{scope}" / name).is_dir()
    return (node_modules / pkg_name).is_dir()
```

## 未来优化方向

1. **依赖版本检查**：检查已安装包的版本是否满足要求
2. **自动更新**：检测新版本并提示更新
3. **离线模式**：支持离线安装依赖
4. **依赖锁定**：生成 lock 文件锁定依赖版本
5. **健康检查**：启动后验证所有依赖是否正常工作
6. **修复工具**：自动修复常见的环境问题
