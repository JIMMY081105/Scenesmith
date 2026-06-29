param(
    [string]$Config = "config.yaml"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    python benchmark.py --config $Config --quick --dry-run
}
finally {
    Pop-Location
}
