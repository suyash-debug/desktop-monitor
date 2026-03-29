@echo off
title Desktop Monitor - Setup
echo ============================================
echo   Desktop Monitor - Automated Setup
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.11+ from https://python.org
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
echo [OK] Python found
python --version

:: Install Python dependencies
echo.
echo [1/3] Installing Python dependencies...
pip install -e . --quiet
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install Python packages.
    pause
    exit /b 1
)
echo [OK] Python packages installed

:: Check Ollama
echo.
echo [2/3] Checking Ollama...
ollama --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Ollama not found.
    echo Please install Ollama from: https://ollama.com/download
    echo After installing, run: ollama pull llama3.2
    echo Then re-run this setup.
    pause
    exit /b 1
)
echo [OK] Ollama found

:: Pull llama3.2 model
echo Pulling llama3.2 model (this may take a few minutes on first run)...
ollama pull llama3.2
echo [OK] llama3.2 ready

:: Check Tesseract (optional, for OCR)
echo.
echo [3/3] Checking Tesseract OCR (optional)...
tesseract --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Tesseract not found - screenshots will be captured but OCR text extraction disabled.
    echo To enable OCR, install from: https://github.com/UB-Mannheim/tesseract/wiki
) else (
    echo [OK] Tesseract found
)

echo.
echo ============================================
echo   Setup Complete!
echo ============================================
echo.
echo To start the monitor, run:  start_monitor.bat
echo Dashboard will open at:     http://127.0.0.1:7001
echo.
pause
