@echo off
REM Сборка в exe (требует установленный pyinstaller: pip install pyinstaller)
pyinstaller --onefile --windowed --name pip_manager src\main.py
echo.
echo Готово. exe-файл в папке dist\pip_manager.exe
pause
