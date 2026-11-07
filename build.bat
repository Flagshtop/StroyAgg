 @echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul || (echo Не найден Python. Установите Python 3.11-3.13 с https://www.python.org/downloads/ ^(галочка "Add to PATH"^) & pause & exit /b 1)
if not exist .venv (
  echo Создаю виртуальное окружение...
  py -3 -m venv .venv || (pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller || (pause & exit /b 1)
echo Сборка StroyAgg.exe...
pyinstaller --noconfirm --clean --windowed --name StroyAgg ^
  --add-data "aggregator\extract.js;aggregator" ^
  --add-data "sites.json;." ^
  --collect-all playwright ^
  app.py || (pause & exit /b 1)
copy /y sites.json dist\StroyAgg\ >nul
copy /y config.ini.example dist\StroyAgg\ >nul
copy /y schema.sql dist\StroyAgg\ >nul
copy /y README.md dist\StroyAgg\ >nul
echo.
echo Готово: dist\StroyAgg\StroyAgg.exe
explorer dist\StroyAgg
pause
