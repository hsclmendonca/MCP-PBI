@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SERVER_SCRIPT=%SCRIPT_DIR%powerbi-mcp-server.py"
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe"
set "LAUNCH_LOG=%SCRIPT_DIR%mcp-launcher.log"
set "DEBUG_LOG=%PBI_MCP_DEBUG_LOG%"

if /I "%DEBUG_LOG%"=="1" (
    echo [%date% %time%] launcher start >> "%LAUNCH_LOG%"
    echo SCRIPT_DIR=%SCRIPT_DIR% >> "%LAUNCH_LOG%"
    echo SERVER_SCRIPT=%SERVER_SCRIPT% >> "%LAUNCH_LOG%"
)

if exist "%PYTHON_EXE%" (
    if /I "%DEBUG_LOG%"=="1" echo using fixed python: %PYTHON_EXE% >> "%LAUNCH_LOG%"
    "%PYTHON_EXE%" "%SERVER_SCRIPT%"
    if /I "%DEBUG_LOG%"=="1" echo fixed python exit code=%ERRORLEVEL% >> "%LAUNCH_LOG%"
    exit /b %ERRORLEVEL%
)

where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    if /I "%DEBUG_LOG%"=="1" echo using py -3 >> "%LAUNCH_LOG%"
    py -3 "%SERVER_SCRIPT%"
    if /I "%DEBUG_LOG%"=="1" echo py -3 exit code=%ERRORLEVEL% >> "%LAUNCH_LOG%"
    exit /b %ERRORLEVEL%
)

where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    if /I "%DEBUG_LOG%"=="1" echo using python from PATH >> "%LAUNCH_LOG%"
    python "%SERVER_SCRIPT%"
    if /I "%DEBUG_LOG%"=="1" echo python PATH exit code=%ERRORLEVEL% >> "%LAUNCH_LOG%"
    exit /b %ERRORLEVEL%
)

echo Python runtime not found. Install Python 3.10+ or pbi-cli-tool. 1>&2
if /I "%DEBUG_LOG%"=="1" echo python runtime not found >> "%LAUNCH_LOG%"
exit /b 1
