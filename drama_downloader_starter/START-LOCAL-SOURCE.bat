@echo off
setlocal EnableExtensions
chcp 65001 >nul
title 短剧搜索助手 - 启动诊断
cd /d "%~dp0"
set "LOG=%~dp0启动诊断日志.txt"
echo ===== 短剧搜索助手启动诊断 ===== > "%LOG%"
echo 时间：%date% %time%>> "%LOG%"
echo 工作目录：%CD%>> "%LOG%"
echo.
echo 此窗口会保持打开，错误会写入“启动诊断日志.txt”。
echo.
where py >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [错误] 未找到 Python Launcher。>> "%LOG%"
  echo 未检测到 Python。当前版本是源码启动包，不能作为免安装软件直接运行。
  echo 请把“启动诊断日志.txt”发给开发者。
  goto :end
)
py -0p >> "%LOG%" 2>&1
py -3 -c "import sys,struct; print(sys.version); print(struct.calcsize('P')*8)" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [错误] 找不到可用的 Python 3。>> "%LOG%"
  echo 找不到可用的 Python 3。请将诊断日志发来。
  goto :end
)
if not exist ".env" copy /y ".env.example" ".env" >> "%LOG%" 2>&1
echo 正在检查依赖，首次启动可能需要联网安装……
py -3 -m pip --version >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [错误] pip 不可用。>> "%LOG%"
  echo Python 的 pip 不可用，请发来诊断日志。
  goto :end
)
py -3 -m pip install -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [错误] 安装依赖失败，详见日志。
  goto :end
)
echo 正在启动本地服务，请不要关闭此窗口……
start "" http://127.0.0.1:8000/
py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >> "%LOG%" 2>&1
if errorlevel 1 echo [错误] 服务启动失败，详见日志。>> "%LOG%"
:end
echo.
echo ===== 诊断结束 =====
echo 日志文件：%LOG%
echo 请把上方错误内容或“启动诊断日志.txt”发回来。
pause
