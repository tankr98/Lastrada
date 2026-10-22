param(
    [string]$Checkpoint = "$HOME\.lastrada_sampleid\sampleid-best.ckpt",
    [int]$Port = 8503,
    [ValidateRange(1, 5)]
    [int]$Candidates = 3,
    [switch]$Install,
    [switch]$SkipModelWarmup
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
    Write-Host "Installing Lastrada, Sony SampleID, and Demucs..."
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r requirements.txt
    powershell -ExecutionPolicy Bypass -File .\scripts\install_sampleid.ps1
    powershell -ExecutionPolicy Bypass -File .\scripts\install_stems.ps1
}

if (-not (Test-Path $Checkpoint)) {
    throw "Sony checkpoint not found at '$Checkpoint'. Pass -Checkpoint with the full path to sampleid-best.ckpt."
}

$env:LASTRADA_SAMPLEID_CHECKPOINT = (Resolve-Path $Checkpoint).Path
$env:LASTRADA_STEM_FAST_MAX_CANDIDATES = "$Candidates"
$env:LASTRADA_STEM_FAST_MODEL = "htdemucs_6s"
$env:LASTRADA_STEM_FAST_DEVICE = "cpu"
$env:LASTRADA_STEM_FAST_PADDING_SECONDS = "4.0"
$env:LASTRADA_STEM_FAST_CROSS_OTHER = "1"
$env:OMP_NUM_THREADS = "2"
$env:MKL_NUM_THREADS = "2"

Write-Host "Checking Sony SampleID..."
& $Python .\scripts\diagnose_sampleid.py
if ($LASTEXITCODE -ne 0) {
    throw "Sony SampleID diagnostics failed. Fix the diagnostic error before starting the website."
}

Write-Host "Checking Demucs..."
& $Python -c "import demucs; print('Demucs import: OK')"
if ($LASTEXITCODE -ne 0) {
    throw "Demucs is not installed in this virtual environment. Re-run with -Install."
}

if (-not $SkipModelWarmup) {
    & $Python .\scripts\prepare_demucs.py `
        --model htdemucs_6s `
        --device cpu `
        --segment 7
    if ($LASTEXITCODE -ne 0) {
        throw "Demucs model preparation failed. Review the terminal error above."
    }
}

Write-Host "Starting the fast stem-assisted site at http://localhost:$Port"
Write-Host "Sony candidates sent to Demucs: top $Candidates"
Write-Host "Press Ctrl+C to stop the website."
& $Python -m streamlit run .\stem_fast_local_app.py `
    --server.address localhost `
    --server.port $Port `
    --browser.gatherUsageStats false
