@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   更新 Kirara AI
echo   文档: https://kirara-docs.app.lss233.com/guide/configuration/update.html
echo ========================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo 尚未初始化。请先双击运行「初始化.cmd」。
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
echo 正在升级 kirara-ai...
python -m pip install -U kirara-ai
if errorlevel 1 (
    echo [错误] 更新失败。
    pause
    exit /b 1
)

echo.
echo 更新完成。data 目录会保留，无需迁移。
echo 请重新运行「启动.cmd」。
pause
