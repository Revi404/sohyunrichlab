@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (set PY=py) else (set PY=python)
%PY% publish.py all
