$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Push-Location $taskRoot
try {
    foreach ($kind in @('data', 'a2a')) {
        $venvPath = ".venv-$kind"
        if (-not (Test-Path -LiteralPath "$venvPath/Scripts/python.exe")) {
            python -m venv $venvPath
            if ($LASTEXITCODE -ne 0) { throw "Create $kind environment failed" }
        }
        & "$venvPath/Scripts/python.exe" -m pip install --cache-dir '.cache/pip' -r "环境/requirements-$kind.lock.txt"
        if ($LASTEXITCODE -ne 0) { throw "Install $kind dependencies failed" }
    }
    docker compose -f '环境/compose.yaml' build ros1
    if ($LASTEXITCODE -ne 0) { throw 'Build ROS image failed' }
    docker compose -f '环境/compose.yaml' up -d ros1 ros2
    if ($LASTEXITCODE -ne 0) { throw 'Start ROS container failed' }
} finally {
    Pop-Location
}
