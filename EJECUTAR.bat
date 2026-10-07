@echo off
chcp 65001 >nul
title Verificador de Obras Sociales v2.0
color 0B
call venv\Scripts\activate.bat
cls
echo ═══════════════════════════════════════════════════════════
echo   VERIFICADOR DE OBRAS SOCIALES v2.0
echo ═══════════════════════════════════════════════════════════
echo.
start "" pythonw.exe gui.py
if errorlevel 1 (
    color 0C
    echo.
    echo El programa se cerró con errores
    echo Revise los logs para más información
    echo.
    pause
)
