@echo off
setlocal
call "%~dp0打包_ASR_GUI.bat" || goto :error
call "%~dp0打包_LLM_GUI.bat" || goto :error
call "%~dp0打包_TTS_GUI.bat" || goto :error
echo.
echo 所有 GUI 可执行文件已生成在 dist\* 目录下。
exit /b 0

:error
echo 发生错误，已中止。
exit /b 1
