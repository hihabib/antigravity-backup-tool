@echo off
title Antigravity 1-Click Restore Tool
color 0E
echo =======================================================
echo          Antigravity 1-Click Restore Tool
echo =======================================================
echo.
echo WARNING: This will restore the latest backup into your
echo Antigravity environment. An automatic safety snapshot
echo will be created prior to restoring.
echo.
set /p confirm="Do you want to proceed with restoring the latest backup? (y/n): "
if /i "%confirm%" neq "y" (
    echo Restore cancelled by user.
    pause
    exit /b 0
)

echo.
python "%~dp0antigravity_backup.py" restore --latest

echo.
pause
