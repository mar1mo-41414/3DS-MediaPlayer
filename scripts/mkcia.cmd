@echo off
rem Wrapper to run the build tool (tool\mkcia) from any directory. Windows counterpart of mkcia.sh.
rem Uses the "py" launcher if present, otherwise "python".
setlocal
set "PYTHONPATH=%~dp0..\tool;%PYTHONPATH%"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m mkcia %*
) else (
    python -m mkcia %*
)
exit /b %errorlevel%
