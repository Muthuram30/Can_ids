@echo off
setlocal
cd /d "%~dp0"
python -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul
if errorlevel 1 goto try_launcher
python scripts\sync_pi.py %*
exit /b %errorlevel%
:try_launcher
py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul
if errorlevel 1 goto missing_python
py -3 scripts\sync_pi.py %*
exit /b %errorlevel%
:missing_python
echo Python 3.9 or later is required. Install Python or add it to PATH.
exit /b 1
