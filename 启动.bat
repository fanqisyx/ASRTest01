@echo off
chcp 65001
cd /d %~dp0
:: 激活conda base环境（推荐用call激活，兼容性更好）
call "%USERPROFILE%\anaconda3\Scripts\activate.bat" base
python main.py
pause
