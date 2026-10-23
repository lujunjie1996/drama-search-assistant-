from __future__ import annotations
import os
import sys
import time
import socket
import threading
import webbrowser
from pathlib import Path

# In a PyInstaller onedir release, user data/config live beside the executable.
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
os.chdir(ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except Exception:
    pass

HOST = "127.0.0.1"
PORT = int(os.getenv("PORT", "8000"))
URL = f"http://{HOST}:{PORT}/"

def port_is_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.4):
            return True
    except OSError:
        return False

def wait_for_server(proc=None, seconds=30) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if port_is_open():
            return True
        if proc is not None and proc.poll() is not None:
            return False
        time.sleep(0.25)
    return False

def main() -> int:
    print("=" * 54)
    print("短剧搜索助手 · Windows 64 位版")
    print("=" * 54)
    if not (ROOT / ".env").exists():
        example = ROOT / ".env.example"
        if example.exists():
            (ROOT / ".env").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            print("已生成默认配置文件 .env。")
    if port_is_open():
        print(f"本机端口 {PORT} 已有服务运行，将打开网页。")
        webbrowser.open(URL)
        return 0
    try:
        import uvicorn
        from app.main import app
    except Exception as exc:
        print(f"程序组件加载失败：{exc}")
        input("请重新解压完整文件夹；若仍失败，请把此错误发给软件提供者。按回车退出……")
        return 1

    def open_browser_when_ready():
        if wait_for_server(seconds=30):
            webbrowser.open(URL)

    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    print(f"正在启动本机服务：{URL}")
    print("浏览器将自动打开。请保持此窗口打开；关闭窗口会停止软件。")
    try:
        uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
    except KeyboardInterrupt:
        print("正在退出……")
    except Exception as exc:
        print(f"启动失败：{exc}")
        input("请确认 8000 端口未被占用。按回车退出……")
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
