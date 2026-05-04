<#
.SYNOPSIS
    Test the Power BI MCP server handshake.
.DESCRIPTION
    Sends an MCP initialize request to the Python MCP server via stdio
    and verifies the response. This validates that the server starts,
    parses Content-Length framing, and responds correctly.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$serverScript = Join-Path $root "scripts\powerbi-mcp-server.py"

Write-Host "`n=== MCP Server Handshake Test ===" -ForegroundColor Cyan

# Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "[FAIL] Python not found" -ForegroundColor Red
    exit 2
}
Write-Host "[OK] Python found" -ForegroundColor Green

# Check server script
if (-not (Test-Path $serverScript)) {
    Write-Host "[FAIL] Server script not found: $serverScript" -ForegroundColor Red
    exit 2
}
Write-Host "[OK] Server script found" -ForegroundColor Green

# Build the initialize request with Content-Length framing
$initRequest = @{
    jsonrpc = "2.0"
    id = 1
    method = "initialize"
    params = @{
        protocolVersion = "2024-11-05"
        capabilities = @{}
        clientInfo = @{
            name = "test-client"
            version = "1.0.0"
        }
    }
} | ConvertTo-Json -Depth 10 -Compress

$body = [System.Text.Encoding]::UTF8.GetBytes($initRequest)
$header = "Content-Length: $($body.Length)`r`n`r`n"
$payload = $header + $initRequest

Write-Host "Sending initialize request..." -ForegroundColor Yellow

try {
    # Start the server process
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "python"
    $psi.Arguments = "`"$serverScript`""
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $process = [System.Diagnostics.Process]::Start($psi)

    # Send the initialize request
    $writer = $process.StandardInput
    $writer.Write($payload)
    $writer.Flush()
    $writer.Close()

    # Read response with timeout
    $task = $process.StandardOutput.ReadToEndAsync()
    $completed = $task.Wait(10000)

    if (-not $completed) {
        $process.Kill()
        Write-Host "[FAIL] Server did not respond within 10 seconds" -ForegroundColor Red
        exit 1
    }

    $response = $task.Result

    if (-not $process.HasExited) {
        $process.Kill()
    }

    # Parse the response - skip Content-Length header
    if ($response -match '(\{.+\})') {
        $jsonResponse = $Matches[1] | ConvertFrom-Json

        if ($jsonResponse.result.serverInfo.name) {
            Write-Host "[OK] Server responded:" -ForegroundColor Green
            Write-Host "  Name: $($jsonResponse.result.serverInfo.name)" -ForegroundColor White
            Write-Host "  Version: $($jsonResponse.result.serverInfo.version)" -ForegroundColor White
            Write-Host "  Protocol: $($jsonResponse.result.protocolVersion)" -ForegroundColor White

            # Now test tools/list
            Write-Host "`nServer handshake successful. Testing tools/list..." -ForegroundColor Yellow

            $toolsRequest = @{
                jsonrpc = "2.0"
                id = 2
                method = "tools/list"
                params = @{}
            } | ConvertTo-Json -Depth 5 -Compress

            $initNotify = @{
                jsonrpc = "2.0"
                method = "notifications/initialized"
                params = @{}
            } | ConvertTo-Json -Depth 5 -Compress

            # Build full payload: initialize + initialized notification + tools/list
            $initBody = [System.Text.Encoding]::UTF8.GetBytes($initRequest)
            $notifyBody = [System.Text.Encoding]::UTF8.GetBytes($initNotify)
            $toolsBody = [System.Text.Encoding]::UTF8.GetBytes($toolsRequest)

            $fullPayload = "Content-Length: $($initBody.Length)`r`n`r`n" + $initRequest
            $fullPayload += "Content-Length: $($notifyBody.Length)`r`n`r`n" + $initNotify
            $fullPayload += "Content-Length: $($toolsBody.Length)`r`n`r`n" + $toolsRequest

            $process2 = [System.Diagnostics.Process]::Start($psi)
            $writer2 = $process2.StandardInput
            $writer2.Write($fullPayload)
            $writer2.Flush()
            $writer2.Close()

            $task2 = $process2.StandardOutput.ReadToEndAsync()
            $task2.Wait(10000) | Out-Null
            $response2 = $task2.Result

            if (-not $process2.HasExited) { $process2.Kill() }

            # Count tools from the tools/list response
            $allMatches = [regex]::Matches($response2, '\{[^{}]*"tools"\s*:\s*\[')
            if ($allMatches.Count -gt 0) {
                # Extract tool names
                $toolNames = [regex]::Matches($response2, '"name"\s*:\s*"(pbi_[^"]+)"')
                $uniqueTools = $toolNames | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique
                Write-Host "[OK] $($uniqueTools.Count) MCP tools registered:" -ForegroundColor Green
                foreach ($tool in $uniqueTools) {
                    Write-Host "  - $tool" -ForegroundColor White
                }
            } else {
                Write-Host "[WARN] Could not parse tools/list response" -ForegroundColor Yellow
            }

            Write-Host "`n=== MCP Server Test PASSED ===" -ForegroundColor Green
            exit 0
        } else {
            Write-Host "[FAIL] Unexpected response format" -ForegroundColor Red
            Write-Host $response
            exit 1
        }
    } else {
        Write-Host "[FAIL] No JSON found in response" -ForegroundColor Red
        Write-Host "Raw output: $response"
        exit 1
    }
}
catch {
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
