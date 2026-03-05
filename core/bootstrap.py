"""
Bootstrap: 启动前自动检查并安装所有依赖。

- Python 依赖：读取 requirements.txt，用 pip 安装缺失的包
- npm 全局包：读取 npm-requirements.txt，用 npm install -g 安装缺失的包
"""

import subprocess
import sys
from pathlib import Path

_already_run = False  # 防止 uvicorn reload 时重复执行


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """在 Windows 上必须 shell=True 才能找到 npm/npx 等命令。"""
    return subprocess.run(cmd, capture_output=True, text=True, shell=True, **kwargs)


def check_python_deps(requirements_file: str = "requirements.txt") -> None:
    req_path = Path(requirements_file)
    if not req_path.exists():
        return
    print("[Bootstrap] 检查 Python 依赖...")
    result = _run([sys.executable, "-m", "pip", "install", "-r", str(req_path), "--quiet"])
    if result.returncode != 0:
        print(f"[Bootstrap] [WARN] pip install 出现问题:\n{result.stderr.strip()}")
    else:
        print("[Bootstrap] [OK] Python 依赖已就绪")


def check_npm_deps(npm_requirements_file: str = "npm-requirements.txt") -> None:
    req_path = Path(npm_requirements_file)
    if not req_path.exists():
        return

    packages = []
    for line in req_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        packages.append(line)

    if not packages:
        return

    print("[Bootstrap] 检查 npm 全局包...")

    # 用 parseable 格式获取已安装全局包，比 --json 快且不易出错
    result = _run(["npm", "ls", "-g", "--depth=0", "--parseable"])
    installed_names: set[str] = set()
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            # Windows 路径可能用 \ 或 /，兼容两种
            name = line.strip().replace("\\", "/").split("/")[-1]
            if name:
                installed_names.add(name)

    missing = []
    for pkg in packages:
        # 提取包名（去掉版本号，如 agent-browser@0.16.3 → agent-browser）
        pkg_name = pkg.split("@")[0] if not pkg.startswith("@") else pkg
        if pkg_name not in installed_names:
            missing.append(pkg)

    if not missing:
        print("[Bootstrap] [OK] npm 全局包已就绪")
        return

    for pkg in missing:
        print(f"[Bootstrap] 安装 npm 包: {pkg} ...")
        result = _run(["npm", "install", "-g", pkg, "--registry=https://registry.npmmirror.com"])
        if result.returncode != 0:
            print(f"[Bootstrap] [WARN] 安装 {pkg} 失败:\n{result.stderr.strip()}")
        else:
            print(f"[Bootstrap] [OK] {pkg} 安装成功")


def run(skip_python: bool = False, skip_npm: bool = False) -> None:
    """执行全部依赖检查。内置防重复执行保护，多次调用只跑一次。"""
    global _already_run
    if _already_run:
        return
    _already_run = True

    if not skip_python:
        check_python_deps()
    if not skip_npm:
        check_npm_deps()
