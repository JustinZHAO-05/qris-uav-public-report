$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3.12 -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install -r requirements.txt

$ibtracsCsv = "data\external\ibtracs.WP.list.v04r01.csv"
$ibtracsZip = "$ibtracsCsv.zip"
if (-not (Test-Path $ibtracsCsv) -and (Test-Path $ibtracsZip)) {
    Expand-Archive -LiteralPath $ibtracsZip -DestinationPath "data\external" -Force
}

.\.venv\Scripts\python.exe src\qris_uav_simulation_v2.py

$matlab = Get-Command matlab -ErrorAction SilentlyContinue
if ($null -eq $matlab -and (Test-Path "D:\Matlab\2024a\bin\matlab.exe")) {
    $matlabPath = "D:\Matlab\2024a\bin\matlab.exe"
} elseif ($null -ne $matlab) {
    $matlabPath = $matlab.Source
} else {
    $matlabPath = $null
}

if ($null -ne $matlabPath) {
    & $matlabPath -batch "run('src/ris_farfield_matlab.m')"
} else {
    Write-Warning "MATLAB was not found. Reusing the committed MATLAB-derived RIS figures in figures_v2."
}

.\.venv\Scripts\python.exe src\build_deck_v2.py
.\.venv\Scripts\python.exe src\verify_outputs_v2.py
