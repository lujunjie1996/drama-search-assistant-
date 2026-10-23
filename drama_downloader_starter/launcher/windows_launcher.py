import os
import sys

base_path = os.path.dirname(os.path.abspath(__file__))
# 往上一层到 drama_downloader_starter，然后把app目录加入搜索路径
proj_root = os.path.abspath(os.path.join(base_path, ".."))
sys.path.insert(0, proj_root)

# 正确导入：app包里面的main，app对象
from app.main import app
import uvicorn

def main():
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
    
