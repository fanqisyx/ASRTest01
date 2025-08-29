@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

echo [TTS] 安装依赖...
python -m pip install -r "TTS_App\requirements.txt" || goto :error
python -m pip install pyinstaller || goto :error

echo [TTS] 清理旧构建...
if exist "build\TTS_App" rmdir /s /q "build\TTS_App"
if exist "dist\TTS_App" rmdir /s /q "dist\TTS_App"

echo [TTS] 打包 GUI 版本...
pyinstaller --noconfirm --clean --windowed ^
  --name TTS_GUI ^
  --distpath "dist\TTS_App" --workpath "build\TTS_App" --specpath "build\TTS_App" ^
  --add-data "TTS_App\config.json;." ^
  "TTS_App\gui.py" || goto :error

echo.
echo [TTS] 打包完成：dist\TTS_App\TTS_GUI.exe
echo.
exit /b 0

:error
echo 发生错误，打包中止。
exit /b 1
