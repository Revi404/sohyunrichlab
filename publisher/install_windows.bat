@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (set PY=py) else (set PY=python)
echo [1/3] 필요한 프로그램 설치
%PY% -m pip install -r requirements.txt
%PY% -m playwright install chromium
echo [2/3] 로그인 (열리는 브라우저에서 티스토리와 네이버에 로그인한 뒤 이 창에서 Enter)
%PY% publish.py login
set /p RUNAT=매일 몇 시에 올릴까요? (예: 21:00, 그냥 Enter 면 21:00) : 
if "%RUNAT%"=="" set RUNAT=21:00
echo [3/3] 매일 %RUNAT% 자동 실행 예약
schtasks /Create /SC DAILY /ST %RUNAT% /TN "SohyunRichlab Publish" /TR "\"%~dp0run_windows.bat\"" /F
echo.
echo 끝났습니다. 예약 확인: 작업 스케줄러 - "SohyunRichlab Publish"
pause
