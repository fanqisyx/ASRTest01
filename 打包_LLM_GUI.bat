@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

echo [LLM] 安装依赖...
python -m pip install -r "LLM_App\requirements.txt" || goto :error
python -m pip install pyinstaller || goto :error

echo [LLM] 清理旧构建...
if exist "build\LLM_App" rmdir /s /q "build\LLM_App"
if exist "dist\LLM_App" rmdir /s /q "dist\LLM_App"

echo [LLM] 打包 GUI 版本...
pyinstaller --noconfirm --clean --windowed ^
  --name LLM_GUI ^
  --distpath "dist\LLM_App" --workpath "build\LLM_App" --specpath "build\LLM_App" ^
  --add-data "LLM_App\config.json;." ^
  --add-data "LLM_App\System_Prompt.txt;." ^
  "LLM_App\gui.py" || goto :error

echo.
echo [LLM] 打包完成：dist\LLM_App\LLM_GUI.exe
echo.
exit /b 0

:error
echo 发生错误，打包中止。
exit /b 1
