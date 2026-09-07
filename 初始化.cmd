@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   Kirara AI QQ 机器人 - 初始化
echo ========================================
echo.

python -V >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python。请先安装 Python 3.12 或更高版本，并勾选 Add to PATH。
    pause
    exit /b 1
)

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
if errorlevel 1 (
    echo [错误] 需要 Python 3.12 或更高版本。当前版本：
    python -V
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo [1/3] 创建虚拟环境...
    python -m venv venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败。
        pause
        exit /b 1
    )
) else (
    echo [1/3] 虚拟环境已存在，跳过创建。
)

call venv\Scripts\activate.bat

echo [2/3] 安装 / 更新 Kirara AI...
python -m pip install -U pip
python -m pip install -U kirara-ai
if errorlevel 1 (
    echo [错误] 安装 kirara-ai 失败，请检查网络后重试。
    pause
    exit /b 1
)

echo [3/3] 生成 QQ 机器人配置...
python scripts\bootstrap_config.py
if errorlevel 1 (
    echo [错误] 生成配置失败。
    pause
    exit /b 1
)

echo.
echo 初始化完成。
echo 请双击「启动.cmd」启动机器人，然后打开 http://127.0.0.1:8080
echo.
pause
