param(
    [string]$Config = "config.yaml"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    python benchmark.py --config $Config --modules stress --stress-calls 20
    python benchmark.py --config $Config --modules structured --structured-calls 20
    python benchmark.py --config $Config --modules resume --resume-total-calls 10 --simulate-crash-every 3 --auto-restart
}
finally {
    Pop-Location
}
