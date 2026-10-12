@echo off
rem ============================================================================
rem  Preflight operable — PASO 6: Ruta del Captain
rem
rem  Codigos de salida:  0 = PASA   2 = BLOCKED   1 = FALLA
rem  BLOCKED significa "falta verificar", NUNCA "verificado".
rem  Este paso NO escribe en el host, no instala, no activa y no llama a nadie.
rem ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"
set "PYEXE="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
  if not errorlevel 1 set "PYEXE=py -3"
)
if not defined PYEXE (
  where python >nul 2>nul
  if not errorlevel 1 set "PYEXE=python"
)
if not defined PYEXE (
  echo Se necesita Python 3.10 o posterior.
  pause
  exit /b 2
)
echo.
%PYEXE% "%~dp0preflight_operable.py" --step 6
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" echo   PASO 6: PASA
if "%RC%"=="1" echo   PASO 6: FALLA
if "%RC%"=="2" echo   PASO 6: BLOCKED ^(falta verificar, no verificado^)
echo.
pause
exit /b %RC%