@echo off
REM Сборка в exe (требует установленный pyinstaller: pip install pyinstaller)
pyinstaller --onefile --windowed --name PipManager src\main.py
echo.
echo Готово. exe-файл в папке dist\
pause
