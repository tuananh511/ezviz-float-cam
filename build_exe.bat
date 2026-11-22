@echo off
setlocal
REM build_exe.bat - build dist\EzvizFloatCam.exe (PyInstaller, onefile, khong hien console)
REM Chay tu thu muc goc repo (ngang hang src\, config\, assets\).
REM
REM Tu chon Python: neu co .venv\ (uv venv) thi dung no, neu khong dung "python" trong PATH.
REM Neu co san file ezvizfloatcam.spec (file nay bi .gitignore, tuy may) thi build theo spec;
REM neu khong co thi build bang tham so duoi day (khong can tao spec).

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

echo [1/2] Kiem tra PyInstaller (dung: %PY%)...
%PY% -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [LOI] Chua co PyInstaller trong moi truong nay. Cai bang MOT trong hai cach:
    echo     uv pip install -r requirements-dev.txt
    echo     python -m pip install -r requirements-dev.txt
    exit /b 1
)
echo     OK.

echo.
echo [2/2] Dang build EzvizFloatCam.exe (onefile)...
if exist ezvizfloatcam.spec (
    echo     Dung ezvizfloatcam.spec co san.
    %PY% -m PyInstaller ezvizfloatcam.spec --noconfirm --clean
) else (
    %PY% -m PyInstaller --noconfirm --clean --onefile --windowed ^
        --name EzvizFloatCam ^
        --icon assets\app_icon.ico ^
        --paths src ^
        --add-data "config\default_config.json;config" ^
        --add-data "assets\app_icon.ico;assets" ^
        src\main.py
)

if errorlevel 1 (
    echo [LOI] Build that bai. Xem log ben tren de biet chi tiet.
    exit /b 1
)

echo.
echo ===================================================
echo  XONG! File .exe nam o: dist\EzvizFloatCam.exe
echo  Luu y: may chay file exe nay van can cai VLC media player.
echo ===================================================
