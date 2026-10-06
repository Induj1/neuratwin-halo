param([switch]$WithoutLaya)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:HALO_AI_ENABLED = if ($WithoutLaya) { '0' } else { '1' }
# Existing environment credentials are inherited; none are created or printed.
# This script never starts the USB bridge or Telegram worker.
if (-not $WithoutLaya) {
    $modelPython = Join-Path $PSScriptRoot '.venv-laya\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $modelPython)) {
        Write-Host 'Local Laya environment is missing. See README.md; rules fallback remains available.'
    } else {
        $modelReady = $false
        try { $modelReady = (Invoke-RestMethod 'http://127.0.0.1:8766/health' -TimeoutSec 2).status -eq 'ok' } catch {}
        if (-not $modelReady) {
            $env:LAYA_HOST='127.0.0.1'; $env:LAYA_PORT='8766'; $env:LAYA_DEVICE='cpu'
            $env:LAYA_MODELS='english'; $env:LAYA_THREADS='4'; $env:LAYA_PRELOAD='1'; $env:LAYA_CPU_AMP='0'
            $env:LAYA_REVISION='7b928d828b7b0e022f929d9bd2e44165aa270148'
            New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot 'runtime') | Out-Null
            Start-Process -FilePath $modelPython -ArgumentList '-m','laya.serve' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'runtime\laya.stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'runtime\laya.stderr.log') | Out-Null
        }
    }
}
Write-Host 'Open http://127.0.0.1:8765/app. Physical controls remain disabled unless separately commissioned and enabled.'
python -m uvicorn neuratwin.app:app --host 127.0.0.1 --port 8765
