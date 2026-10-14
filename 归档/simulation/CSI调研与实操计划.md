> 最新CSI进展（2026-10-14）：[第三阶段方案与结果](../../csi/README.md)。C5单板router基线已完成；Pi4B Nexmon/AX210 PicoScenes保留，Jetson监听与业务关联待验证。本文Atheros路线保留为历史参考/备用。

# 机器狗上行数据与 Wi-Fi CSI 采集计划

更新日期：2026-10-11

## 计划概述

我的计划是先在本机把“传感器样本加编号，经 UDP 分块发送，再在接收端重组”跑通；进实验室后先核对无线设备，再验证 Atheros CSI 链路和业务数据关联，之后才接 Go2 的位置、相机和雷达数据。相机、雷达分开接入，最后再考虑一起跑。

本机 UDP 验证已完成，结果和边界见下文。目前还不知道实验室 TX/RX 的具体型号，也没有刷机或采过真实 CSI；Go2 传感器接口也要到现场确认。因此，下文中涉及硬件的部分是待现场核对后执行的计划，不代表已经实测。

## 调研结果和两个仓库怎么用

查下来，CSI 是按收到的无线包记录的；这套工具分驱动/固件和用户态收发工具两部分，主要面向 ath9k 支持的 Atheros 802.11n 芯片，并不是所有 Atheros 设备都能用。项目列出的已验证芯片有 AR9580、AR9590、AR9344、QCA9558 等，具体设备仍要按完整型号、硬件版本和驱动核对。项目 Wiki 的 AP/Client 采集方式要求 TX、RX 都使用兼容实现。

| 仓库 | 主要内容 | 计划在哪一步用 |
|---|---|---|
| [Atheros_CSI_tool_OpenWRT_src](https://github.com/xieyaxiongfly/Atheros_CSI_tool_OpenWRT_src) | OpenWrt 和 CSI 驱动侧代码，涉及硬件支持及固件准备 | 第 1 步核对 TX/RX 芯片和驱动；如果现有设备没有可用 CSI 固件，再确认型号、镜像和许可后，按这个仓库的说明准备固件 |
| [Atheros_CSI_tool_OpenWRT_UserSpaceApp_src](https://github.com/xieyaxiongfly/Atheros_CSI_tool_OpenWRT_UserSpaceApp_src) | 路由器上运行的用户态工具，包含 sendData、recvCSI 和 MATLAB 解析目录 | 第 2 步用 sendData/recvCSI 跑官方小包测试并解析 CSI；第 3 步沿用接收记录检查自定义 sample_id（这部分需要我自己发包，不是仓库现成功能） |

## 实验安排

下面是我准备按顺序做的完整流程。Jetson 保持实验室现有 Ubuntu/JetPack 环境；OpenWrt 和 CSI 驱动放在兼容的 Atheros TX/RX 节点上，第一轮不改 Jetson 内核，也不在 Jetson 上安装 OpenWrt 或 CSI Tool。

```text
Go2 / 传感器（具体接口现场确认）
  相机 ── 现有 ROS 图像话题或 Go2 SDK/API ──┐
  雷达 ── 现有 ROS 话题或对应型号的 SDK ───┤
  位姿 ── odom / SLAM / TF；SDK2 状态作候选 ─┘
                                                ↓
Jetson Orin NX（Ubuntu / JetPack）
  接收数据 → 按采样时间关联位姿 → 选择并编号样本
  → 封装 sample_id、传感器类型、时间、x/y 和数据
  → 样本需要应用层分块时，再加 chunk_id / chunk_count
                                                │ 网线
                                                ▼
                                      Atheros CSI-TX
                                                │ Wi-Fi
                                                ▼
                                      Atheros CSI-RX
                                       ├─ 转发业务数据到服务器
                                       └─ recvCSI 保存 CSI 记录
                                                ↓
服务器：接收业务数据和导出的 CSI 记录，再按 sample/chunk ID 关联
```

相机优先查现有 ROS 图像话题或 Go2 SDK/API；雷达先确认型号和现有 ROS 话题，再选对应 SDK；位置优先查 odom、SLAM 或 TF，SDK2 状态只作为候选。Jetson 负责传感器数据接收、样本信息整理和 UDP 发送。两个 Atheros 节点负责 CSI 无线链路；TX 到 RX 必须走 Wi-Fi。服务器同时保存业务数据和 CSI 记录，之后按 ID 做关联。实际网络中的桥接、路由、地址和防火墙配置要看现场设备，不能假定插上线就自动转发。

### 本机 UDP 模拟验证

已运行 [udp_sensor_demo.py](CSI本机UDP验证/udp_sensor_demo.py)：在 `127.0.0.1` 上模拟 Jetson 发送相机/雷达样本，接收端按 `sample_id` 和 `chunk_id` 收包并重组。相机样本 4096 字节、6 个应用层数据块，故意倒序到达后仍完整重组且字节校验一致；雷达样本 2500 字节、预期 4 块，演示时故意不发送其中一块，接收端正确判为不完整。共收到 9 个 UDP 数据报。

复现命令：`python simulation/CSI本机UDP验证/udp_sensor_demo.py`。

**结论：** 这个本机验证说明自定义 UDP 头、样本编号、应用层分块和接收端重组可以在本地软件链路中工作；样本 ID 可作为后续关联业务数据的主键，时间和位置随样本保存。它没有经过 Wi-Fi，也没有运行 Atheros CSI Tool、Go2 或真实相机/雷达，所以不能证明真实无线包能读出这些标识，也不能证明一个 UDP 数据报对应一条 CSI。这个对应关系要在实验室用兼容设备另行验证。

### 进实验室后的步骤

1. **盘点设备和数据路径。** 对照驱动仓库记录 TX/RX 的完整型号、硬件版本、无线芯片、驱动和当前固件；确认机器狗数据走哪条无线链路、相机/雷达数据来源及位姿来源。型号或固件不清楚时先核实，不刷机。

2. **先跑 Atheros CSI 基线。** 如果实验室已有兼容设备，先用现成设备；暂时不接机器狗和传感器，让 TX、RX 只通过 Wi-Fi 通信。按用户态仓库用法在 RX 启动 `recvCSI`，在 TX 用 `sendData` 发少量测试包，再用解析程序检查是否得到有效 CSI。记录条数不一定与发包数完全相同。如果设备没有这些命令，先确认目标架构和固件来源，再决定是否编译或部署；不在 Jetson 或本机盲装驱动。

3. **验证业务数据和 CSI 的关联。** 基线测试通过后，发送带 `sample_id`、数据类型和时间戳的小 UDP 包，检查 RX 侧能否从记录载荷中找到标识，并把它与有效 CSI 记录关联。这个 `sample_id` 是我定义的业务字段，不假设官方测试程序已经支持。优先沿用已有消息序号；一个样本可能对应多条 CSI。只有应用程序自己把样本切成多块时，才加 `chunk_id` 和 `chunk_count`。

4. **确认机器狗数据经过被测 Wi-Fi。** 先从 Jetson 发小测试数据到服务器，确认数据确实经过 TX 到 RX 的无线链路，同时 RX 能记录相关 CSI。如果用外接 TX，测到的是外接 TX 到 RX 这一段 Wi-Fi，不是 Jetson 自带无线网卡的 CSI。

5. **再接位姿和传感器。** 按传感器采样时间关联位姿及 `x/y`，先单独接相机或雷达一路，确认样本 ID、位置和 CSI 关联后，再换另一类数据或做多位置测试。

## 数据怎么对应

优先沿用 ROS 或业务数据已有序号；没有时再增加 `sample_id`。每个应用层 UDP 数据块携带 `sample_id`；只有一条样本确实被应用程序切成多块时，才带 `chunk_id/chunk_count`。一个样本可能对应多条 CSI，先确认接收记录能否读出业务标识，再用时间戳辅助匹配。`x/y` 从实际使用的 odom、SLAM、TF 或外部定位取得，并记录坐标系和来源。ROS、Jetson 和无线设备时钟可能不同，没做同步前不要把它们当成同一时间。UDP 数据报、Wi-Fi 帧与 CSI 记录之间的实际映射需要实测，不预设一一对应。

实验室首轮做到两件事就够：RX 能采到有效 CSI；自定义 UDP 业务标识能在相应接收记录中找到并关联。通过后再接机器狗数据和位置。

## 操作前注意

现在不需要为了采 CSI 去改本机 Ubuntu、Docker 或 Jetson。主方案里 Jetson 保持 Ubuntu/JetPack，运行现有 ROS 或 Unitree SDK 和后续的上传程序；OpenWrt、修改后的无线驱动及 `recvCSI` 放在兼容的 Atheros 节点上。真实采集要靠兼容无线设备和驱动。固件编译或刷写前，要先确认设备型号、对应镜像、备份恢复办法和实验室许可；条件不清楚就先不刷。

电脑连路由器的网线用于管理设备；TX 到 RX 的测试数据必须走 Wi-Fi，不能被另一根网线或交换机绕过去。地址、接口名和信道按现场设备确认，不照搬示例值。

## 需要现场确认

- 实验室有哪些能做 TX/RX 的设备？完整型号、硬件版本和当前固件是什么？
- 机器狗上传数据走自带 Wi-Fi，还是可以经过外接 CSI 设备？要测哪一段无线链路？
- 视觉和雷达传的是原始数据、压缩数据、特征还是处理结果？现有消息序号能否复用？
- x、y 从哪个定位话题或设备来，时间戳如何和传感器数据对应？

## 参考资料

- [Atheros CSI Tool 项目](https://github.com/xieyaxiongfly/Atheros_CSI_tool_OpenWRT_src)
- [Atheros CSI Tool OpenWRT 用户态工具（sendData、recvCSI、MATLAB）](https://github.com/xieyaxiongfly/Atheros_CSI_tool_OpenWRT_UserSpaceApp_src)
- [项目 Wiki：CSI 采集方式和 TX/RX 要求](https://github.com/xieyaxiongfly/Atheros_CSI_tool_OpenWRT_src/wiki/Collect-CSI)
- [项目 Wiki：OpenWrt 安装与硬件说明](https://github.com/xieyaxiongfly/Atheros_CSI_tool_OpenWRT_src/wiki/Install-OpenWRT-version-of-Atheros-CSI-tool)
- [OpenWrt 官方：设备刷写说明](https://openwrt.org/docs/guide-user/installation/generic.flashing)
