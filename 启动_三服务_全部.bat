@echo off
chcp 65001 >nul
cd /d %~dp0
setlocal

:: 可选：激活conda或venv环境（按需修改）
REM call "%USERPROFILE%\anaconda3\Scripts\activate.bat" base

start "ASR Service" cmd /k "python services\asr_service.py"
start "LLM Service" cmd /k "python services\llm_service.py"
start "TTS Service" cmd /k "python services\tts_service.py"

endlocal
