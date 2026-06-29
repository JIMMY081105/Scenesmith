param(
    [string]$Config = "config.yaml"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    python benchmark.py --config $Config --modules stress --stress-calls 100
    python benchmark.py --config $Config --modules structured --structured-calls 100
}
finally {
    Pop-Location
}
