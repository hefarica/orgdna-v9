@echo off
rem ============================================================================
rem  ARRANQUE LIMPIO de OrgDNA — envoltorio fino.
rem
rem  Toda la logica vive en arranque_limpio.py, y no por capricho: este lanzador
rem  necesita calcular un SHA-256, hablar HTTP con /api/instance y operar git. Un
rem  .bat no puede hacer ninguna de las tres cosas de forma fiable. Python SI esta
rem  garantizado, porque es el runtime de la propia aplicacion.
rem
rem  Este archivo NO contiene rutas absolutas: usa %~dp0, asi que funciona igual
rem  en C:\ , en un USB o en cualquier copia del repositorio.
rem
rem  Uso:  ARRANQUE_LIMPIO.cmd [--check] [--yes] [--no-update] [--port N]
rem ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PYSET="

rem --- 1) Preferir el lanzador oficial de Windows: py -3 -----------------------
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if not errorlevel 1 (
    set "PYSET=py -3"
    goto :tengo_python
  )
)

rem --- 2) Si no, el python del PATH -------------------------------------------
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if not errorlevel 1 (
    set "PYSET=python"
    goto :tengo_python
  )
)

echo.
echo   FALLO: se necesita Python 3.10 o posterior.
echo.
echo   Este lanzador NO instala programas ni cambia la seguridad de Windows.
echo   Descargalo de https://www.python.org/downloads/ y marca "Add to PATH".
echo.
pause
exit /b 2

:tengo_python
echo.
echo   runtime: !PYSET!
echo.

!PYSET! "%~dp0arranque_limpio.py" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo   Arranque limpio completado.
) else (
  echo   Arranque limpio termino con codigo %RC%. Revisa el detalle de arriba.
)
echo.
pause
exit /b %RC%
