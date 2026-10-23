from __future__ import annotations
import os
import sys
import time
import socket
import subprocess
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
IS_FROZEN = getattr(sys, "frozen", False)

def say(message: str) -> None:
    print(message, flush=True)

def python_in_venv() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"

def port_is_open(host="127.0.0.1", port=8000):
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0

def run(cmd, **kwargs):
    return subprocess.run(cmd, cwd=ROOT, check=True, **kwargs)

def main():
    os.chdir(ROOT)
    say("=" * 56)
    say("短剧搜索助手 - Windows 启动器")
    say("=" * 56)
    if not (ROOT / ".env").exists():
        example = ROOT / ".env.example"
        if example.exists():
            (ROOT / ".env").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            say("已生成 .env 配置文件。请按 README 设置授权下载域名和 API_KEY。")
    if port_is_open():
        say("检测到 127.0.0.1:8000 已有服务运行，正在打开网页。")
        webbrowser.open("http://127.0.0.1:8000/")
        input("按回车退出...")
        return
    py = python_in_venv()
    if not py.exists():
        candidates = []
        for cmd in (["py", "-3.11", "-m", "venv", str(VENV)],
                    ["py", "-3.12", "-m", "venv", str(VENV)],
                    ["python", "-m", "venv", str(VENV)]):
            try:
                say("正在准备 Python 运行环境（首次启动可能需要几分钟）...")
                run(cmd)
                break
            except Exception:
                continue
        if not py.exists():
            say("未找到可用的 Python 3.11+。")
            say("请安装 Python 3.11 或更新版本：https://www.python.org/downloads/")
            input("安装后重新双击启动器。按回车退出...")
            return
    req = ROOT / "requirements.txt"
    if req.exists():
        marker = VENV / ".requirements_installed"
        if not marker.exists():
            say("正在安装依赖，需要联网；这通常只在首次启动执行...")
            try:
                run([str(py), "-m", "pip", "install", "--upgrade", "pip"])
                run([str(py), "-m", "pip", "install", "-r", str(req)])
                marker.write_text("ok", encoding="utf-8")
            except Exception as exc:
                say(f"依赖安装失败：{exc}")
                say("请检查网络后重试，或联系软件提供者。")
                input("按回车退出...")
                return
    say("正在启动网页服务...")
    try:
        proc = subprocess.Popen(
            [str(py), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=ROOT
        )
        for _ in range(40):
            if port_is_open():
                break
            if proc.poll() is not None:
                say("服务启动失败，请检查 .env 和项目文件。")
                input("按回车退出...")
                return
            time.sleep(0.5)
        webbrowser.open("http://127.0.0.1:8000/")
        say("已打开浏览器。请不要关闭这个窗口，关闭窗口会停止服务。")
        proc.wait()
    except KeyboardInterrupt:
        say("正在停止服务...")
        try:
            proc.terminate()
        except Exception:
            pass

if __name__ == "__main__":
    main()
