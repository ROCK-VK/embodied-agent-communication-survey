$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    & '.\.venv-data\Scripts\python.exe' '实验/data_experiment.py'
    if ($LASTEXITCODE -ne 0) { throw 'Data experiment failed' }
    & '.\.venv-a2a\Scripts\python.exe' '实验/a2a_demo.py'
    if ($LASTEXITCODE -ne 0) { throw 'A2A experiment failed' }
    docker compose -f '环境/compose.yaml' up -d --no-build ros1 ros2
    if ($LASTEXITCODE -ne 0) { throw 'Containers failed to start' }
    docker compose -f '环境/compose.yaml' exec -T ros1 bash -lc 'source /opt/ros/noetic/setup.bash; python3 /project/实验/ros1_pipeline.py'
    if ($LASTEXITCODE -ne 0) { throw 'ROS1 experiment failed' }
    New-Item -ItemType Directory -Path '结果/ROS1' -Force | Out-Null
    docker cp 'embodied-sim-ros1:/workspaces/catkin_ws/experiment-results/ros1/.' '结果/ROS1'
    if ($LASTEXITCODE -ne 0) { throw 'ROS1 results copy failed' }
    docker compose -f '环境/compose.yaml' exec -T ros2 bash -lc 'source /opt/ros/humble/setup.bash; python3 /project/实验/ros2_comparison.py'
    if ($LASTEXITCODE -ne 0) { throw 'ROS2 experiment failed' }
    New-Item -ItemType Directory -Path '结果/ROS2' -Force | Out-Null
    docker cp 'embodied-sim-ros2:/workspaces/ros2/results/.' '结果/ROS2'
    if ($LASTEXITCODE -ne 0) { throw 'ROS2 results copy failed' }
    & '.\.venv-data\Scripts\python.exe' '实验/receiver_training.py'
    if ($LASTEXITCODE -ne 0) { throw 'Receiver training failed' }
    & '.\.venv-data\Scripts\python.exe' '实验/audit_results.py'
    if ($LASTEXITCODE -ne 0) { throw 'Results audit failed' }
    & '.\.venv-data\Scripts\python.exe' '实验/build_report.py'
    if ($LASTEXITCODE -ne 0) { throw 'Report build failed' }
} finally {
    # Stop only this project's services. No global prune, shutdown, or deletion.
    docker compose -f '环境/compose.yaml' stop ros1 ros2
    Pop-Location
}
