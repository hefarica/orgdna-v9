@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if not errorlevel 1 (
    py -3 -m engine.launcher %*
    goto :done
  )
)
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if not errorlevel 1 (
    python -m engine.launcher %*
    goto :done
  )
)
echo Se necesita Python 3.10 o posterior desde python.org.
echo Este lanzador no instala programas ni cambia la seguridad de Windows.
:done
pause
endlocal
