@echo off
title Build Scrcpy Pro Launcher v5 (Tauri)
color 0B

echo ====================================================
echo  🚀 Membangun Scrcpy Pro Launcher v5 (Rust + Tauri)
echo ====================================================
echo.

:: Pindah ke direktori tempat batch file ini berada
cd /d "%~dp0"

echo [1/4] Mengecek dependencies (Node.js dan Rust)...
where npm >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] npm tidak ditemukan. Pastikan Node.js terinstal.
    pause
    exit /b
)
where cargo >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] cargo (Rust) tidak ditemukan. Pastikan Rust sudah diinstal dan terminal di-restart.
    pause
    exit /b
)
echo ✅ Dependencies siap!
echo.

echo [2/4] Menginstal dependencies frontend (npm install)...
call npm install
echo.

echo [3/4] Membangun file .exe (Ini akan memakan waktu pada percobaan pertama)...
call npm run tauri build

if %errorlevel% neq 0 (
    echo.
    echo ❌ [ERROR] Gagal membangun aplikasi! Silakan cek pesan error di atas.
    pause
    exit /b
)

echo.
echo [4/4] Menyalin hasil build...
:: Copy file exe ke root folder (di luar v5)
copy /y "src-tauri\target\release\scrcpy-launcher-v5.exe" "..\Scrcpy-Launcher-v5.exe" >nul

echo.
echo ====================================================
echo  ✨ BUILD SUKSES! ✨
echo ====================================================
echo File .exe kamu sudah jadi dan siap digunakan:
echo 📂 %~dp0Scrcpy-Launcher-v5.exe
echo.
pause
