# 短剧搜索助手（Windows x64 免 Python 打包工程）

本工程提供黑金风格的本地网页界面、授权素材目录导入/搜索、下载任务和任务进度接口。默认仅监听 `127.0.0.1`。

## 最终使用者
使用构建生成的 `短剧助手-Windows-x64-免Python.zip`：解压后双击 `短剧助手/短剧助手.exe`。不需要安装 Python，也不需要命令行。

## 构建 Windows 版
推荐 GitHub Actions：将工程放入自己的 GitHub 仓库，在 Actions 中运行 **Build Windows 64-bit portable release**。构建会在 Windows x64 runner 上打包，并实际启动 EXE 检查 `/health` 与首页；通过后输出 ZIP artifact。

也可以在 Windows x64 电脑上安装 Python 3.12 x64 后运行 `在Windows上生成EXE.bat`。这一步仅供打包者；最终使用者不需要 Python。

## 配置与权限
默认 `.env` 不设置 API key，适合仅本机个人使用。下载源必须是用户拥有或明确获授权的 HTTPS 视频地址，且其域名需加入 `ALLOWED_DOWNLOAD_HOSTS`。平台首页/开放平台 API 不代表有权下载任意视频。合并视频需要另行安装 FFmpeg。

## 重要说明
当前开发环境为 Linux，因此此 ZIP 本身不含已编译的 Windows EXE。Windows 构建工作流包含实际启动测试；只有构建任务成功、smoke test 通过后生成的 ZIP，才是完成该轮验证的 Windows 运行包。
