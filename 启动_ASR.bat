@echo off
chcp 65001 >nul
cd /d %~dp0
setlocal
REM call "%USERPROFILE%\anaconda3\Scripts\activate.bat" base
python services\asr_service.py
endlocal
pause
