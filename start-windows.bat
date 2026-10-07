@echo off
title InvestTrack
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo Python is not installed.
  echo Install it from https://www.python.org/downloads/
  echo During setup, tick "Add python.exe to PATH". Then double-click this file again.
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First start: setting things up. This takes a few minutes...
  %PY% -m venv .venv
  if errorlevel 1 goto error
)
".venv\Scripts\python.exe" launch.py
if errorlevel 1 goto error
exit /b 0

:error
echo.
echo Something went wrong. Take a screenshot of this window and share it.
pause
exit /b 1
