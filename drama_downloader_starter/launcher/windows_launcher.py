import os
import sys
import uvicorn

def main():
    base_path = os.path.dirname(os.path.abspath(__file__))
    # 主程序入口：假设你的api服务入口文件是 main.py，在 drama_downloader_starter 根目录
    # 如果你的服务入口文件名不是 main.py，后面告诉我，我再改这一行
    sys.path.insert(0, base_path)
    uvicorn.run("main:app", host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
