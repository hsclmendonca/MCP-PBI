@echo off
setlocal

set "ROOT=%~dp0"
pushd "%ROOT%" >nul 2>&1

where powershell >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [FAIL] PowerShell was not found in PATH.
    echo Install Windows PowerShell 5.1+ and try again.
    popd
    exit /b 1
)

echo.
echo === Power BI MCP + Agent (1-Click Startup) ===
echo Repository: %ROOT%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\start-agent-mcp-core.ps1" -OpenInCode
set "EXIT_CODE=%ERRORLEVEL%"

if %EXIT_CODE% NEQ 0 (
    echo.
    echo [FAIL] Startup failed with exit code %EXIT_CODE%.
    echo Run scripts\doctor-local.ps1 for diagnostics.
    popd
    exit /b %EXIT_CODE%
)

echo.
echo [OK] Local MCP + Agent startup completed.
echo VS Code should now be open and ready.

popd
exit /b 0
