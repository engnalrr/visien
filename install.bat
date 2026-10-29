@echo off
cd /d "%~dp0"
title Visien setup
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo.
  echo Setup stopped with an error. Details: install.log
)
echo.
pause
