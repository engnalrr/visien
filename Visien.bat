@echo off
cd /d "%~dp0"
set "PYW=runtime\python\pythonw.exe"
if not exist "%PYW%" set "PYW=.venv\Scripts\pythonw.exe"
if not exist "%PYW%" (
  echo Visien is not installed yet. Run install.bat first.
  pause
  exit /b 1
)
start "" "%PYW%" -m visien
