@echo off
rem Wrapper to start the GUI (tool\mkcia\gui.py). Windows counterpart of mkcia-gui.sh.
rem Uses pyw (no console window) if present, otherwise python.
setlocal
set "PYTHONPATH=%~dp0..\tool;%PYTHONPATH%"
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 -m mkcia.gui %*
) else (
    python -m mkcia.gui %*
)
