@echo off
REM build_exe.bat — Sprint 6
REM Chạy file này từ thư mục gốc repo (ngang hàng src\, config\).
REM Tự kiểm tra + cài PyInstaller nếu thiếu, sau đó build ra dist\EzvizFloatCam.exe

echo [1/2] Kiem tra PyInstaller...
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo     Chua co PyInstaller, dang cai dat tu requirements-dev.txt...
    python -m pip install -r requirements-dev.txt
    if errorlevel 1 (
        echo [LOI] Cai PyInstaller that bai. Kiem tra lai Python/pip roi thu lai.
        exit /b 1
    )
) else (
    echo     Da co san.
)

echo.
echo [2/2] Dang build EzvizFloatCam.exe (che do onefile)...
REM LUU Y (vu icon): file ezvizfloatcam.spec khong nam trong repo (bi
REM .gitignore loai vi *.spec la file build sinh/tuy may). Neu spec cua
REM ban chua tro toi icon rieng, mo ezvizfloatcam.spec, tim doi tuong EXE(...)
REM va them tham so:  icon='assets\app_icon.ico'
REM (file .ico da co san trong assets\ tu Sprint 8 - vu icon)
pyinstaller ezvizfloatcam.spec --noconfirm

if errorlevel 1 (
    echo [LOI] Build that bai. Xem log ben tren de biet chi tiet.
    exit /b 1
)

echo.
echo ===================================================
echo  XONG! File .exe nam o: dist\EzvizFloatCam.exe
echo  Luu y: may chay file exe nay van can cai VLC media player.
echo ===================================================
