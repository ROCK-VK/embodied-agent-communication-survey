$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Push-Location $taskRoot
try {
    & '.\.venv-data\Scripts\python.exe' -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Data dependencies failed' }
    & '.\.venv-data\Scripts\python.exe' '环境/check_data.py'
    if ($LASTEXITCODE -ne 0) { throw 'Data smoke failed' }
    & '.\.venv-a2a\Scripts\python.exe' -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'A2A dependencies failed' }
    & '.\.venv-a2a\Scripts\python.exe' '环境/check_a2a.py'
    if ($LASTEXITCODE -ne 0) { throw 'A2A smoke failed' }
    docker compose -f '环境/compose.yaml' up -d --no-build ros1
    if ($LASTEXITCODE -ne 0) { throw 'ROS container failed to start' }
    $rosResult = docker compose -f '环境/compose.yaml' exec -T ros1 bash -lc 'source /opt/ros/noetic/setup.bash; python3 /project/环境/check_ros1.py'
    if ($LASTEXITCODE -ne 0) { throw 'ROS smoke failed' }
    $rosResult | Set-Content -LiteralPath '环境/验收产物/ros1-check.json' -Encoding utf8
    Write-Output $rosResult
    Write-Output 'All environment checks passed.'
} finally {
    Pop-Location
}
