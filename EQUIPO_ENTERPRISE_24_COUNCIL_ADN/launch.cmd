@echo off
rem ============================================================================
rem  OrgDNA — launch.cmd
rem
rem  Delega en el ARRANQUE LIMPIO cuando esta disponible (..\arranque_limpio.py,
rem  en la raiz del repositorio). Ese motor verifica el sello, actualiza desde el
rem  repo sin pisar nada, detecta la instancia obsoleta y arranca el codigo NUEVO.
rem
rem  Si el motor NO esta (el paquete se extrajo suelto, sin el repositorio), cae
rem  al comportamiento ORIGINAL del paquete: `python -m engine.launcher`. Asi el
rem  paquete sigue funcionando por si solo.
rem
rem  La interfaz documentada NO cambia y se reenvia tal cual (%*):
rem    launch.cmd --port 0                  pide un puerto libre
rem    launch.cmd --port 9000               prefiere 9000
rem    launch.cmd --port 9000 --strict-port exige 9000
rem    launch.cmd --no-browser              no abre el navegador
rem
rem  Y ademas acepta, solo cuando el motor esta presente:
rem    launch.cmd --check      diagnostico sin tocar nada
rem    launch.cmd --yes        sin preguntas
rem    launch.cmd --no-update  no consulta el repo
rem ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"

rem --- 1) Localizar un Python 3.10+ -------------------------------------------
set "PYEXE="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
  if not errorlevel 1 set "PYEXE=py -3"
)
if not defined PYEXE (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
  )
)
if not defined PYEXE goto :sin_python

rem --- 2) Arranque limpio, si el motor esta en la raiz del repositorio ---------
rem  Se evita el bloque entre parentesis a proposito: %ERRORLEVEL% se expandiria
rem  al PARSEAR el bloque, antes de ejecutar el motor, y devolveria un codigo viejo.
set "MOTOR=%~dp0..\arranque_limpio.py"
if not exist "%MOTOR%" goto :respaldo
%PYEXE% "%MOTOR%" %*
set "RC=%ERRORLEVEL%"
goto :fin

rem --- 3) Respaldo: comportamiento original del paquete ------------------------
:respaldo
%PYEXE% -m engine.launcher %*
set "RC=%ERRORLEVEL%"
goto :fin

:sin_python
echo.
echo Se necesita Python 3.10 o posterior desde python.org.
echo Este lanzador no instala programas ni cambia la seguridad de Windows.
set "RC=2"

:fin
echo.
pause
exit /b %RC%
