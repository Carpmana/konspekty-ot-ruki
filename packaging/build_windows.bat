@echo off
rem Сборка Konspekt.exe на Windows. Запускать из корня репозитория.
rem Нужен Python 3.10+. Интернет нужен только для установки библиотек.
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt pyinstaller || exit /b 1
pyinstaller --noconfirm --clean packaging\konspekt.spec || exit /b 1
echo.
echo Готово: dist\Konspekt\Konspekt.exe
