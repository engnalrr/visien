@echo off
rem Opens Visien in your web browser instead of the app window (fallback).
cd /d "%~dp0"
set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Visien is not installed yet. Run install.bat first.
  pause
  exit /b 1
)
title Visien (browser mode) - close this window to quit
"%PY%" -m visien --browser
