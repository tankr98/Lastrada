param(
    [string]$Checkpoint = "$HOME\.lastrada_sampleid\sampleid-best.ckpt",
    [int]$Port = 8502,
    [switch]$Install
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "Creating a Python 3.12 virtual environment..."
    py -3.12 -m venv .venv
    $Install = $true
}

if ($Install) {
    Write-Host "Installing the Sony + DTW application dependencies..."
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r requirements.txt
    powershell -ExecutionPolicy Bypass -File .\scripts\install_sampleid.ps1
}

if (-not (Test-Path $Checkpoint)) {
    throw "Sony checkpoint not found at '$Checkpoint'. Pass -Checkpoint with the full path to sampleid-best.ckpt."
}

$env:LASTRADA_SAMPLEID_CHECKPOINT = (Resolve-Path $Checkpoint).Path

# Prevent settings left over from the Demucs branch from affecting this process.
$StemVariables = @(
    "LASTRADA_STEM_ENABLED",
    "LASTRADA_STEM_MODEL",
    "LASTRADA_STEM_DEVICE",
    "LASTRADA_STEM_MAX_CANDIDATES",
    "LASTRADA_STEM_PADDING_SECONDS",
    "LASTRADA_STEM_CROSS_OTHER"
)
foreach ($Name in $StemVariables) {
    Remove-Item "Env:$Name" -ErrorAction SilentlyContinue
}

Write-Host "Checking Sony SampleID..."
& $Python .\scripts\diagnose_sampleid.py
if ($LASTEXITCODE -ne 0) {
    throw "Sony SampleID diagnostics failed. Fix the diagnostic error before starting the website."
}

Write-Host "Starting Sony + DTW only at http://localhost:$Port"
Write-Host "Press Ctrl+C to stop the website."
& $Python -m streamlit run .\sony_dtw_local_app.py `
    --server.address localhost `
    --server.port $Port `
    --browser.gatherUsageStats false
