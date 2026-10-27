@echo off
rem Wrapper to start the GUI (tool\mkcia\gui.py). Windows counterpart of mkcia-gui.sh.
rem Python is chosen by the PYTHON environment variable, else the "py" launcher, else python / python3.
setlocal
set "PYTHONPATH=%~dp0..\tool;%PYTHONPATH%"
call :findpython
if not defined PY (
    call :nopython
    exit /b 1
)
rem Check tkinter first in this console, because the GUI is started without one (errors would vanish).
%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    %PY% -m mkcia.gui
    exit /b 1
)
rem Start with pythonw (no console window) if it sits next to this Python, otherwise plain.
for /f "delims=" %%P in ('%PY% -c "import sys,os; w=os.path.join(os.path.dirname(sys.executable),'pythonw.exe'); print(w if os.path.exists(w) else sys.executable)"') do set "PYGUI=%%P"
start "" "%PYGUI%" -m mkcia.gui %*
exit /b 0

:findpython
rem Pick the first candidate that really runs Python 3. The "python" that opens the Microsoft Store is
rem only a stub (it prints "Python" and fails with 9009), so each candidate is tried before it is used.
set "PY="
if defined PYTHON (
    "%PYTHON%" -c "import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)" >nul 2>nul
    if not errorlevel 1 (
        set PY="%PYTHON%"
        goto :eof
    )
)
for %%C in ("py -3" "python" "python3") do (
    %%~C -c "import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "PY=%%~C"
        goto :eof
    )
)
goto :eof

:nopython
echo Error: no working Python 3 was found. 1>&2
echo   "python" on this PC may only be the Microsoft Store shortcut (it prints just "Python"). 1>&2
echo   Install Python 3 from https://www.python.org/downloads/ (or: winget install Python.Python.3.12), 1>&2
echo   then open a new terminal. To use a specific Python: set PYTHON=C:\path\to\python.exe 1>&2
goto :eof
