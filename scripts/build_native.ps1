$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $root 'native\qc_core.cpp'
$out = Join-Path $root 'quillancode\bin\qc_core.exe'
New-Item -ItemType Directory -Force (Split-Path -Parent $out) | Out-Null
$clang = 'C:\Program Files\LLVM\bin\clang++.exe'
if (-not (Test-Path $clang)) { $clang = 'clang++' }
& $clang -O3 -std=c++17 -o $out $src
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output "built $out"
& $out glob $root '*.md' 5
& $out validate $root 'README.md'
& $out read $root 'README.md' 0 2
& $out hash $root 'README.md'
