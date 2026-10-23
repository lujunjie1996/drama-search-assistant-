@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 短剧助手 - Windows x64 免 Python 打包
echo =====================================================
echo   短剧助手 Windows x64 免 Python 打包
echo   此脚本供构建者使用；普通使用者只需双击短剧助手.exe
echo =====================================================
where py >nul 2>nul
if errorlevel 1 (
  echo 构建需要 Python 3.12 x64；最终使用者不需要 Python。
  echo https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
py -3.12 -c "import struct,sys; sys.exit(0 if struct.calcsize('P')*8==64 else 1)"
if errorlevel 1 (echo 请安装 64 位 Python 3.12。& pause & exit /b 1)
if not exist ".build-venv\Scripts\python.exe" py -3.12 -m venv .build-venv
if not exist ".build-venv\Scripts\python.exe" (echo 无法创建打包环境。& pause & exit /b 1)
call .build-venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :failed
pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :failed
if exist "dist\短剧助手" rmdir /s /q "dist\短剧助手"
if exist "build" rmdir /s /q "build"
pyinstaller --noconfirm --clean --onedir --console --name "短剧助手" --distpath "dist" --workpath "build" --add-data "app;app" --add-data "config;config" --collect-all fastapi --collect-all starlette --collect-all uvicorn --collect-all aiohttp --collect-all dotenv --collect-all pydantic --collect-all pydantic_core --collect-all anyio --collect-all h11 --collect-all click launcher\desktop_launcher.py
if errorlevel 1 goto :failed
copy /y ".env.example" "dist\短剧助手\.env.example" >nul
copy /y "WINDOWS-README.txt" "dist\短剧助手\使用说明.txt" >nul
if not exist "dist\短剧助手\data" mkdir "dist\短剧助手\data"
echo.
echo 构建完成：dist\短剧助手\短剧助手.exe
echo 请将整个“短剧助手”文件夹压缩发送，不能只发 EXE。
echo 使用者无需安装 Python；首次运行不需要在线安装 Python 依赖。
echo.
pause
exit /b 0
:failed
echo.
echo 构建失败，请检查上方错误信息和网络连接。
pause
exit /b 1
