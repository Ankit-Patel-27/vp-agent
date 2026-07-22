@echo off
REM VP Agent v4 — Windows launcher
REM Usage:
REM   start.bat                       no AI
REM   start.bat sk-ant-YOUR-KEY       Claude AI
REM   start.bat gsk_YOUR-GROQ-KEY     Groq AI
REM   start.bat AIzaSy-GEMINI-KEY     Gemini AI

cd /d "%~dp0"

if not "%1"=="" (
    set KEY=%1
    echo %KEY% | findstr /C:"gsk_" >nul && set GROQ_API_KEY=%KEY% && echo Using Groq AI
    echo %KEY% | findstr /C:"AIza" >nul && set GEMINI_API_KEY=%KEY% && echo Using Gemini AI
    echo %KEY% | findstr /C:"sk-ant" >nul && set ANTHROPIC_API_KEY=%KEY% && echo Using Claude AI
)

echo Installing dependencies...
pip install -q flask flask-cors requests feedparser yfinance

echo.
echo ======================================================
echo   VP AGENT v4 - Starting...
echo ======================================================
echo   Dashboard : http://localhost:5000
echo   Journal   : http://localhost:5000/journal
echo ======================================================
echo.

python server.py
pause
