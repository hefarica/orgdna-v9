@echo off
setlocal
cd /d "%~dp0"
echo OrgDNA isolated Chromium checks: synthetic data only, no live provider or DSH.
echo This script launches Chromium only on the computer where you choose to run it.
echo It does not install dependencies, attach to OrgDNA, or use your real credentials.
where node >nul 2>nul || (echo Install Node.js 22 LTS from nodejs.org first. & exit /b 2)
node -e "if(process.versions.node.split('.')[0]!=='22')process.exit(1)" || (echo Use Node.js 22 LTS for this pinned suite. & exit /b 2)
if not defined ORGDNA_E2E_PYTHON set "ORGDNA_E2E_PYTHON=python"
"%ORGDNA_E2E_PYTHON%" --version || (echo Set ORGDNA_E2E_PYTHON to your Python 3.11+ executable. & exit /b 2)
if not exist node_modules\.bin\playwright.cmd (
  echo Dependencies are absent. After reviewing docs/CHROMIUM_E2E.md, run:
  echo   npm install --ignore-scripts
  echo   node_modules\.bin\playwright.cmd install chromium
  exit /b 2
)
set PYTHONDONTWRITEBYTECODE=1
"%ORGDNA_E2E_PYTHON%" -m unittest discover -s . -p "test_*fixture.py" || exit /b 1
if /i "%~1"=="--headless" (
  call node_modules\.bin\playwright.cmd test
) else (
  call node_modules\.bin\playwright.cmd test --headed
)
exit /b %ERRORLEVEL%
