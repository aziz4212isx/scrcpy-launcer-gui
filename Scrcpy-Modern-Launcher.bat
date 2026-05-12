@echo off
setlocal enabledelayedexpansion
TITLE Scrcpy Modern Launcher - Auto Builder
COLOR 0A

echo ============================================
echo   Scrcpy Modern Launcher - Auto Updater
echo ============================================
echo.

:: ============================================================
:: CEK PYTHON
:: ============================================================
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python tidak ditemukan! Install Python dan tambahkan ke PATH.
    pause & exit /b
)

:: ============================================================
:: INSTALL DEPENDENSI YANG BELUM ADA
:: ============================================================
echo [INFO] Memeriksa dependensi...

python -c "import customtkinter" >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [INSTALL] Menginstall customtkinter...
    pip install customtkinter -q
)

python -c "import sounddevice" >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [INSTALL] Menginstall sounddevice...
    pip install sounddevice -q
)

python -c "import PyInstaller" >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [INSTALL] Menginstall pyinstaller...
    pip install pyinstaller -q
)

:: ============================================================
:: CEK APAKAH .PY LEBIH BARU DARI .EXE -> AUTO BUILD ULANG
:: Gunakan Python untuk compare timestamp (lebih reliable dari PS)
:: ============================================================
SET "PY_FILE=%~dp0scrcpy_launcher.py"
SET "EXE_FILE=%~dp0Scrcpy-Modern-Launcher.exe"

IF NOT EXIST "%EXE_FILE%" (
    echo [INFO] EXE belum ada, akan dibuild pertama kali...
    GOTO BUILD
)

echo [INFO] Membandingkan waktu modifikasi...

:: Gunakan Python untuk compare — lebih reliable dari PowerShell
python -c "import os,sys; py=r'%PY_FILE%'; exe=r'%EXE_FILE%'; sys.exit(0 if os.path.getmtime(py) > os.path.getmtime(exe) else 1)"

IF %ERRORLEVEL% EQU 0 (
    echo [INFO] scrcpy_launcher.py lebih baru dari EXE, membangun ulang...
    GOTO BUILD
) ELSE (
    echo [INFO] EXE sudah up-to-date, tidak perlu build ulang.
    GOTO LAUNCH
)

:BUILD
echo.
echo [BUILD] Membangun EXE dengan PyInstaller, harap tunggu...
echo.

:: Cek apakah icon tersedia (opsional)
SET "ICON_ARG="
IF EXIST "%~dp0icon.ico" SET "ICON_ARG=--icon=%~dp0icon.ico"
IF EXIST "%~dp0icon.png" SET "ICON_ARG=--icon=%~dp0icon.png"

python -m PyInstaller --noconfirm --onefile --windowed ^
    %ICON_ARG% ^
    --name "Scrcpy-Modern-Launcher" ^
    "%PY_FILE%" ^
    --distpath "%~dp0_dist_tmp"

IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Build gagal! Menjalankan langsung via Python sebagai fallback...
    RMDIR /S /Q "%~dp0_dist_tmp" >nul 2>&1
    RMDIR /S /Q "%~dp0build"     >nul 2>&1
    DEL /F /Q "%~dp0Scrcpy-Modern-Launcher.spec" >nul 2>&1
    GOTO RUN_PYTHON
)

echo.
echo [INFO] Memastikan aplikasi lama tertutup...

:: Ganti EXE lama dengan yang baru
:TRY_MOVE
:: Hentikan EXE lama jika sedang berjalan agar file tidak terkunci (locked)
taskkill /F /IM "Scrcpy-Modern-Launcher.exe" >nul 2>&1
:: Beri jeda 1 detik agar sistem operasi sempat melepas kuncian file
timeout /T 1 /NOBREAK >nul

MOVE /Y "%~dp0_dist_tmp\Scrcpy-Modern-Launcher.exe" "%EXE_FILE%" >nul
IF %ERRORLEVEL% NEQ 0 (
    echo [INFO] File masih digunakan oleh Windows, memaksa tutup dan mencoba lagi...
    GOTO TRY_MOVE
)

RMDIR /S /Q "%~dp0_dist_tmp" >nul 2>&1
RMDIR /S /Q "%~dp0build"     >nul 2>&1
DEL /F /Q "%~dp0Scrcpy-Modern-Launcher.spec" >nul 2>&1

echo.
echo [BUILD] Selesai! Meluncurkan EXE baru...

:LAUNCH
start "" "%EXE_FILE%"
exit

:RUN_PYTHON
echo [INFO] Menjalankan langsung via Python...
start "" pythonw "%PY_FILE%"
exit
