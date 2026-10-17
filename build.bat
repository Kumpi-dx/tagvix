@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  Build TagVix (Omron CP1E -^> MySQL)
echo ============================================================

echo.
echo [1/3] Install dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install --upgrade pyinstaller

echo.
echo [2/3] Build executable...
python -m PyInstaller --clean --noconfirm tagvix.spec

echo.
echo Copying config next to the executable...
if not exist "dist\tagvix\config" mkdir "dist\tagvix\config"
copy /Y "config\config.ini" "dist\tagvix\config\config.ini" >nul

echo.
echo [3/3] Selesai.
echo Hasil build: dist\tagvix\tagvix.exe
echo Config       : dist\tagvix\config\config.ini
echo.
pause
