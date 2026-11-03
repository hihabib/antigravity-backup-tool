@echo off
title Antigravity 1-Click Backup Tool
color 0B
echo =======================================================
echo          Antigravity 1-Click Automated Backup
echo =======================================================
echo.

:: Run python backup tool
python "%~dp0antigravity_backup.py" backup

echo.
pause
