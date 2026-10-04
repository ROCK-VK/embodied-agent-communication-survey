param([switch]$RefreshOfficialDocs)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
$dataPython=Join-Path $projectRoot '.venv-data/Scripts/python.exe'
$a2aPython=Join-Path $projectRoot '.venv-a2a/Scripts/python.exe'
if(!(Test-Path -LiteralPath $dataPython) -or !(Test-Path -LiteralPath $a2aPython)){throw '请先按项目环境说明恢复两套专用虚拟环境。'}
$previousEncoding=$env:PYTHONIOENCODING
$env:PYTHONIOENCODING='utf-8'
function Invoke-PhaseScript($python,$name){
    & $python (Join-Path $PSScriptRoot ('实验/'+$name+'.py'))
    if($LASTEXITCODE -ne 0){throw ('阶段失败：'+$name)}
}
try{
    & $a2aPython -c 'import sqlalchemy, aiosqlite'
    if($LASTEXITCODE -ne 0){
        & $a2aPython -m pip install -r (Join-Path $PSScriptRoot '环境/requirements-a2a.lock.txt') --cache-dir (Join-Path $projectRoot '.cache/pip')
        if($LASTEXITCODE -ne 0){throw '本项目A2A SQLite依赖恢复失败。'}
    }
    & $dataPython -m pip check
    if($LASTEXITCODE -ne 0){throw '数据环境依赖检查失败。'}
    & $a2aPython -m pip check
    if($LASTEXITCODE -ne 0){throw 'A2A环境依赖检查失败。'}
    if($RefreshOfficialDocs -or !(Test-Path -LiteralPath (Join-Path $projectRoot '日志/下一阶段/module_update.html'))){
        Invoke-PhaseScript $dataPython 'fetch_unitree_docs'
    }
    Invoke-PhaseScript $dataPython 'device_profiles'
    Invoke-PhaseScript $dataPython 'image_selection'
    Invoke-PhaseScript $dataPython 'surrogate_optimum'
    docker compose -f (Join-Path $PSScriptRoot 'compose.yaml') build sender
    if($LASTEXITCODE -ne 0){throw '本项目网络镜像构建失败。'}
    Invoke-PhaseScript $dataPython 'network_suite'
    Invoke-PhaseScript $dataPython 'receiver_learning'
    Invoke-PhaseScript $a2aPython 'a2a_workflow'
    Invoke-PhaseScript $a2aPython 'capture_environment'
    Invoke-PhaseScript $dataPython 'audit_phase2'
    Invoke-PhaseScript $dataPython 'build_phase2_report'
    Write-Output '下一阶段全流程复现与报告生成通过。所有结果均为本地模拟。'
} finally{
    docker compose -f (Join-Path $PSScriptRoot 'compose.yaml') stop
    $env:PYTHONIOENCODING=$previousEncoding
}
