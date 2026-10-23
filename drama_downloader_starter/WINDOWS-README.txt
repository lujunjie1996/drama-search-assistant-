短剧助手 Windows x64 免 Python 运行版说明

【普通使用者】
1. 解压“短剧助手-Windows-x64-免Python.zip”。
2. 打开解压后的“短剧助手”文件夹。
3. 双击“短剧助手.exe”。浏览器会自动打开 http://127.0.0.1:8000/ 。
4. 保持黑色启动窗口打开；关闭窗口会停止软件。
5. 任务数据库和下载文件保存在同一文件夹的 data 目录。

【无需做的事】
- 不需要安装 Python。
- 不需要手动 pip 安装依赖。
- 不需要输入命令。

【功能边界】
- 软件提供授权素材目录导入、搜索、下载任务和进度查看。它不会自动获得各平台的短剧下载权限。
- 下载前需将自有或已获授权的视频源 HTTPS 域名写入 .env 的 ALLOWED_DOWNLOAD_HOSTS。默认不配置任何下载域名，避免误下载未经授权的内容。
- 合并视频需要系统中另行安装 FFmpeg；不影响启动、网页界面及分集下载。
- 如 Windows Defender 或杀毒软件提示风险，请先确认文件来源。PyInstaller 打包的未签名程序可能出现误报。

【给构建者】
当前 ZIP 是源代码与自动构建配置，不是已经编译的 Windows EXE。可在 GitHub Actions 的 Actions 页面手动运行“Build Windows 64-bit portable release”，等待 smoke test 通过后，在运行结果 Artifacts 下载“短剧助手-Windows-x64-免Python.zip”。该流程会实际启动 EXE，并测试 /health 与首页。也可在 Windows x64、Python 3.12 x64 环境双击“在Windows上生成EXE.bat”构建。
