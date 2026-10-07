@echo off
chcp 65001 >nul
title Instalación - Verificador de Obras Sociales
color 0A

echo ═══════════════════════════════════════════════════════════
echo     INSTALACIÓN DEL VERIFICADOR DE OBRAS SOCIALES
echo ═══════════════════════════════════════════════════════════
echo.

:: Verificar si Python está instalado
echo [1/5] Verificando Python...
python --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo ❌ ERROR: Python no está instalado.
    echo.
    echo Por favor instale Python desde: https://www.python.org/downloads/
    echo Asegúrese de marcar "Add Python to PATH" durante la instalación.
    echo.
    pause
    exit /b 1
)
echo ✓ Python encontrado
echo.

:: Verificar si el archivo .env existe
echo [2/5] Verificando configuración...
if not exist ".env" (
    color 0E
    echo ⚠️  ADVERTENCIA: No se encontró el archivo .env
    echo.
    echo Por favor configure sus API Keys en el archivo .env antes de continuar.
    echo Presione cualquier tecla para continuar de todos modos...
    pause >nul
    color 0A
)
echo ✓ Archivo .env encontrado
echo.

:: Crear entorno virtual
echo [3/5] Creando entorno virtual...
if exist "venv" (
    echo ✓ El entorno virtual ya existe
) else (
    python -m venv venv
    if errorlevel 1 (
        color 0C
        echo ❌ ERROR: No se pudo crear el entorno virtual
        pause
        exit /b 1
    )
    echo ✓ Entorno virtual creado exitosamente
)
echo.

:: Activar entorno virtual e instalar dependencias
echo [4/5] Instalando dependencias...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    color 0C
    echo ❌ ERROR: Falló la instalación de dependencias
    echo.
    echo Intente ejecutar manualmente: pip install -r requirements.txt
    pause
    exit /b 1
)
echo ✓ Todas las dependencias instaladas correctamente
echo.

:: Crear EJECUTAR.bat
echo [6/7] Creando archivo de ejecución...
(
echo @echo off
echo chcp 65001 ^>nul
echo title Verificador de Obras Sociales v2.0
echo color 0B
echo call venv\Scripts\activate.bat
echo cls
echo echo ═══════════════════════════════════════════════════════════
echo echo   VERIFICADOR DE OBRAS SOCIALES v2.0
echo echo ═══════════════════════════════════════════════════════════
echo echo.
echo start "" pythonw.exe gui.py
echo if errorlevel 1 (
echo     color 0C
echo     echo.
echo     echo El programa se cerró con errores
echo     echo Revise los logs para más información
echo     echo.
echo     pause
echo ^)
) > EJECUTAR.bat
echo ✓ Archivo EJECUTAR.bat creado
echo.

:: CREAR ACCESO DIRECTO EN EL ESCRITORIO
echo [7/7] Creando acceso directo en el escritorio...

(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo Set Shortcut = WshShell.CreateShortcut^("%USERPROFILE%\Desktop\Chequeo App.lnk"^)
    echo Shortcut.TargetPath = "%CD%\EJECUTAR.bat"
    echo Shortcut.WorkingDirectory = "%CD%"
    echo Shortcut.Description = "Chequeo App"
    echo Shortcut.IconLocation = "%CD%\icon.ico"
    echo Shortcut.Save
) > CreateShortcut.vbs

cscript //nologo CreateShortcut.vbs
del CreateShortcut.vbs

echo [OK] Acceso directo creado en el escritorio
echo.

:: Verificar si se creó
if exist "%USERPROFILE%\Desktop\Chequeo App.lnk" (
    echo ✓ Acceso directo creado en el escritorio
) else (
    echo  No se pudo crear el acceso directo en el escritorio
    echo    Puede ejecutar manualmente EJECUTAR.bat desde esta carpeta
)
echo.

color 0B
echo ═══════════════════════════════════════════════════════════
echo            ✓ INSTALACIÓN COMPLETADA EXITOSAMENTE
echo ═══════════════════════════════════════════════════════════
echo.
echo Para ejecutar el programa:
echo    1. Haga doble clic en EJECUTAR.bat
echo    2. O ejecute este archivo nuevamente
echo.
echo ¿Desea iniciar el programa ahora? (S/N)
choice /c SN /n /m "Presione S para SÍ o N para NO: "
if errorlevel 2 goto fin
if errorlevel 1 goto ejecutar

:ejecutar
cls
call EJECUTAR.bat
goto fin

:fin
echo.
echo Gracias por usar el Verificador de Obras Sociales
timeout /t 3 >nul
exit
