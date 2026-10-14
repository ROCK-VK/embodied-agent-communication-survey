# 宇树与 Orin NX 基础操作调研

核验日期：2026-10-04。完成的是官方资料阅读、配置假设和模拟核验，没有连接设备。

## 1. 学长给的链接究竟是什么

[module_update](https://support.unitree.com/home/zh/developer/module_update) 的标题是“拓展坞配置”。它包括连接显示器、拓展坞网络访问、服务更新、接口问题和系统备份恢复等内容。页面列出 Go2 拓展坞地址 `192.168.123.18`，并出现 Go2 NX 的 JetPack5.1.1 出厂镜像名称。因此，Go2 EDU 配 NX 拓展坞是合理的工作假设，但仍不是实际型号的确认。

本轮没有下载系统镜像、刷盘、修改设备树或运行运动例程。官网正文通过该页面实际使用的公开资料接口取得；7篇资料的访问日、页面更新时间和内容哈希见 [核验清单](结果/宇树官方资料核验.json)。全文快照仅保存在本地日志，报告不复制整篇文档。

## 2. 硬件与软件假设

| 项目 | 已知事实 | 本轮工作假设/边界 |
|---|---|---|
| Jetson | 学长称 Orin NX Developer Kit | 以 Go2 NX 拓展坞的16GB配置作为一个模拟档案；8GB作为备选。容量、载板未确认 |
| 机器狗 | 学长提供宇树文档 | Go2 EDU 仅作示例；不能用这个假设排除 Go1/B2 等实际型号 |
| 系统 | 实机版本未知 | 假设 JetPack5.1.1 / Jetson Linux35.3.1 / Ubuntu20.04 / aarch64 |
| ROS | 学长说两代均用，ROS1 更多 | ROS1 为上层研究主线；ROS2/DDS 为可能的设备接口与扩展 |
| 本机 | Windows/x86、Noetic与Humble容器 | 验证接口与算法，不能模拟ARM/GPU指令、功耗或Jetson时延 |

JetPack5.1.1 的官方版本关系为 Ubuntu20.04 / L4T35.3.1；JetPack6.2 使用 Ubuntu22.04 系列环境。它们是明确版本的资料对照，不是在建议升级实机。[NVIDIA 5.1.1](https://docs.nvidia.com/jetson/jetpack/5.1.1/release-notes/index.html)、[NVIDIA 6.2](https://docs.nvidia.com/jetson/jetpack/6.2/release-notes/index.html)

Orin NX 模组与载板是两个需要分别确认的对象；“Developer Kit”这个名称不能推出具体载板或现有镜像。第三方载板适配可能涉及设备树和启动配置。[NVIDIA 载板适配](https://docs.nvidia.com/jetson/archives/r36.5/DeveloperGuide/HR/JetsonModuleAdaptationAndBringUp/JetsonOrinNxNanoSeries.html)

## 3. 拿到设备后的只读核查顺序

以下是待实机执行的步骤，不是本轮已执行记录。

1. 核对设备铭牌、模组与载板，记录现有系统版本；先保留原配置，不以模拟档案覆盖设备。
2. 查看系统、架构和软件版本：

```bash
uname -m
cat /etc/os-release
cat /etc/nv_tegra_release
dpkg-query -W nvidia-l4t-core nvidia-jetpack
printenv ROS_DISTRO RMW_IMPLEMENTATION ROS_DOMAIN_ID
```

3. 查看网卡和路由，区分 PC、机器人内部电脑、拓展坞。Go2 示例中 `.161` 与 `.18` 是不同角色；PC 可用同子网的空闲地址，不得冲突。真实IP以现有配置为准。[宇树快速开始](https://support.unitree.com/home/zh/developer/Quick_start)

```bash
ip -brief address
ip route
ping -c 3 192.168.123.161
ping -c 3 192.168.123.18
```

4. 在当前终端只加载目标 ROS 环境，观察话题类型、发布频率和消息；ROS1 与 ROS2 不混写到全局 `.bashrc`。

```bash
# ROS1：已存在配置的情况下查看，不自动改 ROS_MASTER_URI
rosversion -d
rosnode list
rostopic list
rostopic info /实际感知话题
rostopic hz /实际感知话题
# ROS2：在匹配的独立终端
ros2 topic list
ros2 topic info /实际感知话题
```

5. 明确模型、相机/雷达消息格式与时间基准，再采集短时离线样本。帧率、序号、时间戳、`frame_id`、单位、版本和消息字节量都应记录。

没有连接设备时，ping、SSH、话题观察和SDK编译成功都不能写为已验证。本轮仅使用 [模拟设备档案](结果/设备假设核验.json) 检查版本关系、ARM架构和IP冲突。

## 4. ROS1 更多并不等于机器人底层是 ROS1

宇树 [架构说明](https://support.unitree.com/home/zh/developer/Architecture%20Description) 列明模块间DDS、App侧WebRTC、网络配置BLE及云侧MQTT/HTTP等职责；SDK2 和 ROS2 接口有明确的DDS背景。

官方 [unitree_ros2 固定提交](https://github.com/unitreerobotics/unitree_ros2/blob/668d1ec5a05d1c38d3306bdca7d59f2ba3581a88/README.md) 说明 CycloneDDS/RMW、类型和网卡配置。首阶段的 Fast DDS 演示仅说明通用 ROS2 消息机制，不能当作宇树接入验收。ROS1/TCPROS不能直接订阅DDS，若真实项目采用ROS1，需要SDK到ROS1适配器或经ROS2的类型转换桥；目前未完成宇树原生消息桥接。

候选路径：设备DDS/SDK → 只读感知适配器 → ROS1感知话题 → 价值筛选 → 接收/训练；A2A在其上组织分析任务。不要把运动状态消息直接当成视觉感知模型的训练数据。

Noetic已于2025-05-31结束支持。本项目为匹配学长现有ROS1研究而保留隔离模拟环境，不据此建议新设备无条件采用该版本。[Open Robotics说明](https://discourse.ros.org/t/ros-noetic-end-of-life-may-31-2025/43160)

## 5. 常见问题的检查方向

| 现象 | 先查什么 | 本轮是否实机验证 |
|---|---|---|
| ping不通 | 接线、实际网卡、地址冲突、子网、路由 | 否 |
| ROS1能列话题但没数据 | Master地址之外，还需节点互相解析并连接发布端；不是只开放11311端口 | 已在隔离容器验证节点互通；设备未验证 |
| ROS2没有发现 | Domain、网卡、DDS实现、消息类型、组播和QoS | 首阶段通用QoS已验证；宇树具体配置未验证 |
| 数据到达但训练退化 | 过期/重复、类别覆盖、标注质量、感知模型失配 | 新阶段模拟验证 |
| A2A断线后找不到任务 | 任务ID、服务是否重启、TaskStore是否持久化 | 新阶段已用官方SQLite TaskStore验证完成任务重启查询 |

WiFi AP/STA、4G与局域网SDK链路是不同角色，不能把“联网了”直接等同可接入指定DDS接口。[宇树网络服务](https://support.unitree.com/home/zh/developer/network%20service)
