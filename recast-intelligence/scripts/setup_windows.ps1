# One-time setup on Windows: creates a virtual environment and installs dependencies.
# Run from PowerShell in the recast-intelligence folder:  powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created .env - open it and fill in your keys." }
Write-Host "Setup complete. Next: edit .env, then run:  .\.venv\Scripts\python.exe -m recast_intel doctor"
