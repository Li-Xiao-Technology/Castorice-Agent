@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM   Castorice Agent v2.0 - Windows One-Click Launcher
REM   Double-click to run, or run from cmd.exe
REM   For PowerShell use:  cmd /c start.bat
REM ============================================================

REM Clear proxy environment variables to fix pip connection issues
set HTTP_PROXY=
set HTTPS_PROXY=
set http_proxy=
set https_proxy=

title Castorice Agent v2.0
cd /d "%~dp0"

echo.
echo ============================================================
echo    Castorice Agent v2.0 - One-Click Start
echo ============================================================
echo.

REM ---------- Step 1: Detect Python ----------
echo [1/5] Detecting Python...
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

REM ---------- Step 2: Detect package manager ----------
echo.
echo [2/5] Detecting package manager...
set USE_UV=0

uv --version >nul 2>&1
if not errorlevel 1 (
    echo [OK] uv found
    set USE_UV=1
    goto pkg_mgr_done
)

echo [WARN] uv not found, falling back to pip
goto pkg_mgr_done

:pkg_mgr_done

REM ---------- Step 3: Create virtual environment ----------
echo.
echo [3/5] Preparing virtual environment...
if exist "venv\Scripts\python.exe" (
    echo [OK] Existing venv found
    goto venv_ready
)

if exist "venv" (
    echo [WARN] Found incomplete venv, removing...
    rmdir /s /q "venv"
)

echo    Creating venv...
if %USE_UV%==1 (
    uv venv venv --python 3.10
) else (
    %PYTHON_CMD% -m venv venv
)
if errorlevel 1 (
    echo [ERR] Failed to create virtual environment
    pause
    exit /b 1
)
echo [OK] Virtual environment created

:venv_ready
set VENV_PYTHON=%CD%\venv\Scripts\python.exe

REM HuggingFace mirror for China network
set HF_ENDPOINT=https://hf-mirror.com

REM ---------- Step 4: Install dependencies ----------
echo.
echo [4/5] Installing dependencies...

if %USE_UV%==1 (
    uv pip install -e .
) else (
    "%VENV_PYTHON%" -m pip install -e . --quiet
)

if errorlevel 1 (
    echo [ERR] Dependency installation failed
    pause
    exit /b 1
)
echo [OK] Dependencies installed

REM ---------- Step 5: Check .env and launch ----------
echo.
echo [5/5] Launching Castorice Agent...
echo.

if not exist ".env" (
    if exist ".env.example" (
        echo [WARN] .env not found, copying from .env.example
        copy .env.example .env >nul
        echo [OK] .env created. Please edit it with your API keys.
        echo.
        pause
        exit /b 0
    )
    echo [WARN] .env.example not found, proceeding...
)

echo Starting interactive mode...
echo.
"%VENV_PYTHON%" -m castorice.main --mode interactive

if errorlevel 1 (
    echo.
    echo [ERR] Program exited with error
    pause
)

endlocal
