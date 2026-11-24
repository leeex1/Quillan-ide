$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$desktop = Join-Path $root 'desktop'
Set-Location $desktop
node --check main.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
node --check preload.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output 'desktop sources syntax OK'
if (-not (Test-Path (Join-Path $desktop 'node_modules\electron'))) {
  npm install --save-dev electron electron-builder
}
npx electron-builder --win nsis
