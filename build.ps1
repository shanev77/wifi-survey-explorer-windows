param([switch]$SkipTests,[switch]$Standalone,[switch]$Both)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { py -3 -m venv .venv }
$python=Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
if (-not $SkipTests) {
 & $python -m pytest tests -q
 if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
}
& $python scripts/collect_licenses.py
& $python scripts/make_demo.py
if ($LASTEXITCODE -ne 0) { throw 'Demo generation failed' }
try {
 if ($Both) { $env:WIFI_ONEFILE='both' } elseif ($Standalone) { $env:WIFI_ONEFILE='1' } else { $env:WIFI_ONEFILE='0' }
 & $python -m PyInstaller --noconfirm WiFiSurveyExplorer.spec
 if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }
} finally { Remove-Item Env:WIFI_ONEFILE -ErrorAction SilentlyContinue }
