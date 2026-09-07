@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo 尚未初始化。请先双击运行「初始化.cmd」。
    pause
    exit /b 1
)

if not exist "data\config.yaml" (
    echo 缺少 data\config.yaml。请先运行「初始化.cmd」。
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
echo 正在启动 Kirara AI...
echo WebUI: http://127.0.0.1:8080
echo 监听: 0.0.0.0:8080 （QQ 开放平台 Webhook 需要公网可达）
echo.
python -m kirara_ai -H 0.0.0.0 -p 8080
echo.
echo 进程已退出。
pause
