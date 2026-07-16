@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM   Castorice Agent v2.0 - Install Only (no launch)
REM   Use this if you want to set up the environment first,
REM   then launch manually later.
REM ============================================================

title Castorice Agent - Install
cd /d "%~dp0"

echo.
echo ============================================================
echo    Castorice Agent v2.0 - Install Dependencies Only
echo ============================================================
echo.

REM ---------- Step 1: Detect Python ----------
echo [1/4] Detecting Python...
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
echo [2/4] Detecting package manager, uv preferred...
set USE_UV=0

uv --version >nul 2>&1
if not errorlevel 1 (
    echo [OK] uv found, using uv
    set USE_UV=1
    goto pkg_mgr_done
)

echo [WARN] uv not found, falling back to pip
echo         Tip: install uv via  pip install uv
goto pkg_mgr_done

:pkg_mgr_done

REM ---------- Step 3: Create virtual environment ----------
echo.
echo [3/4] Preparing virtual environment...
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

REM ---------- Step 4: Install dependencies ----------
echo.
echo [4/4] Installing dependencies...

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

REM ---------- Check .env ----------
echo.
if not exist ".env" (
    if exist ".env.example" (
        echo [WARN] .env not found, copying from .env.example
        copy .env.example .env >nul
        echo [OK] .env created. Please edit it with your API keys.
    )
)

echo.
echo ============================================================
echo    Installation complete!
echo    To start:  double-click start.bat
echo    Or run:    venv\Scripts\python -m castorice.main --mode interactive
echo ============================================================
echo.
pause
endlocal
