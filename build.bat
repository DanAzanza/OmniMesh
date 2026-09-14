@echo off
setlocal
title OmniMesh Extension Builder

:: Navigate to project root directory
cd /d "%~dp0"

echo ===================================================
echo   OmniMesh - Building Blender Extension Package
echo ===================================================
echo.

python scripts\build_extension.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Build failed with error code %ERRORLEVEL%.
    echo Please verify that Python is installed and available in PATH.
    echo.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [SUCCESS] Extension package built successfully! Check the 'dist' folder.
echo.
pause
