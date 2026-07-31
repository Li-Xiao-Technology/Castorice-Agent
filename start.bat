@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM   Castorice Agent v2.0 - One-Click Launcher
REM   双击运行，或在 cmd.exe 中执行
REM   PowerShell 用户请直接运行:  powershell -ExecutionPolicy Bypass -File launch.ps1
REM ============================================================

REM 清除代理环境变量
set HTTP_PROXY=
set HTTPS_PROXY=
set http_proxy=
set https_proxy=

title Castorice Agent v2.0
cd /d "%~dp0"

echo.
echo ============================================================
echo    Castorice Agent v2.0 - Starting...
echo ============================================================
echo.

REM ---------- Step 1: 检查 Python ----------
echo [1/4] Checking Python...
set PYTHON_CMD=

python --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=python
    goto python_found
)

py --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=py
    goto python_found
)

echo [ERR] Python not found. Please install Python 3.10+ first.
echo         https://www.python.org/downloads/
pause
exit /b 1

:python_found
%PYTHON_CMD% --version
echo [OK] Python detected

REM ---------- Step 2: 检查虚拟环境 ----------
echo.
echo [2/4] Checking virtual environment...

if not exist "venv\Scripts\python.exe" (
    if exist "venv" (
        echo [WARN] Found incomplete venv, removing...
        rmdir /s /q "venv"
    )
    echo    Creating venv...
    %PYTHON_CMD% -m venv venv
    if errorlevel 1 (
        echo [ERR] Failed to create virtual environment
        pause
        exit /b 1
    )
)
echo [OK] Virtual environment ready

REM ---------- Step 3: 安装依赖 ----------
echo.
echo [3/4] Installing dependencies...
set VENV_PYTHON=%CD%\venv\Scripts\python.exe

set HF_ENDPOINT=https://hf-mirror.com
"%VENV_PYTHON%" -m pip install -e . --quiet

if errorlevel 1 (
    echo [ERR] Dependency installation failed
    pause
    exit /b 1
)
echo [OK] Dependencies installed

REM ---------- Step 4: 检查 .env ----------
echo.
echo [4/4] Checking configuration...

if not exist ".env" (
    if exist ".env.example" (
        echo [WARN] .env not found, copying from .env.example
        copy .env.example .env >nul
        echo [OK] .env created. Please edit it with your API keys.
        echo.
        pause
        exit /b 0
    )
)
echo [OK] Configuration ready

REM ---------- Step 5: 调用 PowerShell 启动脚本（单实例 + 前后端绑定） ----------
echo.
echo ============================================================
echo    Launching services (single instance, frontend+backend)
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1"

if errorlevel 1 (
    echo.
    echo [ERR] Launch failed
    pause
)

endlocal
