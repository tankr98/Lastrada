$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Revision = "e212b0b9974d52d334cc793ef1b8cabaf251e5f8"
$DefaultSource = Join-Path $RepoRoot "vendor\sampleid-upstream"
$ModelRoot = if ($env:LASTRADA_SAMPLEID_SOURCE) {
    $env:LASTRADA_SAMPLEID_SOURCE
} else {
    $DefaultSource
}

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. From the repository root run: py -3.12 -m venv .venv"
}

Write-Host "Installing Sony SampleID runtime dependencies..."
& $Python -m pip install --upgrade pip
& $Python -m pip install "torch>=2.6,<3" "hydra-core>=1.3,<2" "tqdm>=4.66,<5"

if (-not (Test-Path $ModelRoot)) {
    New-Item -ItemType Directory -Force (Split-Path -Parent $ModelRoot) | Out-Null
    git clone https://github.com/sony/sampleid.git $ModelRoot
}

$CurrentRevision = (git -C $ModelRoot rev-parse HEAD).Trim()
if ($CurrentRevision -ne $Revision) {
    git -C $ModelRoot fetch --all --tags
    git -C $ModelRoot checkout $Revision
}

$Dirty = git -C $ModelRoot status --porcelain
if ($Dirty) {
    throw "The Sony SampleID source at '$ModelRoot' has local changes. Preserve or clean them before continuing."
}

Write-Host "Installing Sony SampleID from source in editable mode..."
& $Python -m pip uninstall -y sampleid | Out-Null
& $Python -m pip install --no-deps -e $ModelRoot

Write-Host "Verifying the checkpoint model import path..."
& $Python -c "from sampleid import SampleID; import sampleid; import src.networks.resnet_ibn; print('sampleid:', sampleid.__file__); print('Sony model target import: OK')"

Write-Host ""
Write-Host "Sony SampleID source installation is ready."
Write-Host "Next run: .\.venv\Scripts\python.exe scripts\diagnose_sampleid.py"
