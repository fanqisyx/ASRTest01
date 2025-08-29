@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

echo [ASR] 安装依赖...
python -m pip install -r "ASR_App\requirements.txt" || goto :error
python -m pip install pyinstaller || goto :error

echo [ASR] 清理旧构建...
if exist "build\ASR_App" rmdir /s /q "build\ASR_App"
if exist "dist\ASR_App" rmdir /s /q "dist\ASR_App"

echo [ASR] 打包 GUI 版本...
pyinstaller --noconfirm --clean --windowed ^
  --name ASR_GUI ^
  --distpath "dist\ASR_App" --workpath "build\ASR_App" --specpath "build\ASR_App" ^
  --add-data "ASR_App\config.json;." ^
  --add-data "ASR_App\mic_guard.txt;." ^
  --add-data "ASR_App\提示音.wav;." ^
  "ASR_App\gui.py" || goto :error

echo.
echo [ASR] 打包完成：dist\ASR_App\ASR_GUI.exe
echo.
exit /b 0

:error
echo 发生错误，打包中止。
exit /b 1
