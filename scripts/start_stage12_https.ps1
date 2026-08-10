# Start the local Stage 12 server with HTTPS for phone camera testing.
# The certificate and private key are generated under data/dev_https, which is
# ignored by Git. This is a development certificate, not a production one.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$certDir = Join-Path $repoRoot "data\dev_https"
$pythonExe = (Get-Command python).Source
python (Join-Path $repoRoot "scripts\generate_dev_https_cert.py") --output-dir $certDir --ip "192.168.31.83"
$certPath = Join-Path $certDir "bambuddy-dev.crt"
$keyPath = Join-Path $certDir "bambuddy-dev.key"
$oldListener = Get-NetTCPConnection -LocalPort 8019 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($oldListener) {
  Stop-Process -Id ([int]$oldListener.OwningProcess) -Force
  Start-Sleep -Milliseconds 500
}
$logPath = Join-Path $env:TEMP "bambuddy-stage12-https-server.log"
$errorPath = Join-Path $env:TEMP "bambuddy-stage12-https-server-error.log"
Start-Process -FilePath $pythonExe -ArgumentList @(
  "-m", "uvicorn", "backend.app.main:app",
  "--host", "0.0.0.0", "--port", "8019", "--loop", "asyncio",
  "--ssl-certfile", $certPath, "--ssl-keyfile", $keyPath
) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $logPath -RedirectStandardError $errorPath
Write-Host "HTTPS server started: https://192.168.31.83:8019/"
Write-Host "If the phone warns about the development certificate, install/accept it only on your private test network."
