import subprocess
import time
import sys

def run(cmd):
    print(f"\n> Running: {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print(f"✅ Success:\n{result.stdout}")
        else:
            print(f"❌ Failed (Code {result.returncode}):\n{result.stderr}\n{result.stdout}")
        return result.returncode == 0
    except Exception as e:
        print(f"💥 System Error: {e}")
        return False

def main():
    print("=== Agent-Browser 诊断脚本 ===")
    
    # 1. 检查版本
    if not run("agent-browser --version"):
        print("尝试使用 npx 版本...")
        if not run("npx agent-browser --version"):
            print("❌ 核心工具未找到，请确保已运行 npm install -g agent-browser")
            return

    # 2. 检查/安装浏览器依赖
    print("\n正在检查浏览器二进制文件 (Chromium)...")
    run("agent-browser install")

    # 3. 尝试重置/启动会话并打开页面
    print("\n正在尝试打开网页 (example.com)...")
    # 强制关闭可能存在的残留进程
    run("agent-browser close") 
    
    if run("agent-browser open https://example.com"):
        print("\n正在尝试获取快照 (Snapshot)...")
        run("agent-browser snapshot -i")
    else:
        print("\n❌ 无法打开页面。这通常是由于 Playwright 环境或权限问题。")
        print("提示：尝试运行 'npx playwright install-deps chromium' 安装系统依赖。")

    print("\n=== 诊断结束 ===")

if __name__ == "__main__":
    main()
