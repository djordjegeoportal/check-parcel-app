@echo off
title Parcela Finder - Pokretanje
color 0A
echo.
echo  ================================================
echo    PARCELA FINDER - GeoSrbija ^> Google Maps + PDF
echo  ================================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] Python nije instaliran.
    echo  Otvaram stranicu za download...
    echo  VAZNO: Oznaci "Add Python to PATH" pri instalaciji!
    echo.
    start https://www.python.org/downloads/
    pause
    exit /b
)

echo  [OK] Python pronadjen.
echo.
echo  Instaliram potrebne pakete (prvi put moze potrajati ~2 min)...
echo.

pip install requests pyproj reportlab qrcode pillow --quiet --disable-pip-version-check 2>nul
if %errorlevel% neq 0 (
    pip install requests pyproj reportlab qrcode pillow --quiet --user --disable-pip-version-check
)

echo  [OK] Paketi instalirani.
echo.
echo  Pokrecem Parcela Finder...
echo.

set "DIR=%~dp0"
python "%DIR%parcela_finder_v3.py"

if %errorlevel% neq 0 (
    echo.
    echo  [!] Greska pri pokretanju.
    echo  Proverite da li je parcela_finder_v3.py u istom folderu.
    pause
)
