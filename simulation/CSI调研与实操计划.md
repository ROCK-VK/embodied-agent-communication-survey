# 机器狗上行数据与 Wi-Fi CSI 采集计划

更新日期：2026-10-10

## 计划概述

我准备先确认实验室现有无线设备能不能用 Atheros CSI Tool，再从简单链路开始：TX 发测试包，RX 采 CSI；接着用带 sample_id 的小 UDP 数据验证业务数据和 CSI 能不能对应；这一步通过后，再接机器狗的数据和位置。相机、雷达分开测，最后再考虑一起跑。

目前我只完成了资料调研和计划整理，还不知道实验室 TX/RX 的具体型号，也没有刷机或采过真实 CSI。所以下一步先盘点设备，确认条件后再动手。

## 调研结果和两个仓库怎么用

查下来，CSI 是按收到的无线包记录的；这套工具分驱动/固件和用户态收发工具两部分，主要面向 ath9k 支持的 Atheros 802.11n 芯片，并不是所有 Atheros 设备都能用。项目列出的已验证芯片有 AR9580、AR9590、AR9344、QCA9558 等，具体设备仍要按完整型号、硬件版本和驱动核对。项目 Wiki 的 AP/Client 采集方式要求 TX、RX 都使用兼容实现。

| 仓库 | 主要内容 | 计划在哪一步用 |
|---|---|---|
| [Atheros_CSI_tool_OpenWRT_src](https://github.com/xieyaxiongfly/Atheros_CSI_tool_OpenWRT_src) | OpenWrt 和 CSI 驱动侧代码，涉及硬件支持及固件准备 | 第 1 步核对 TX/RX 芯片和驱动；如果现有设备没有可用 CSI 固件，再确认型号、镜像和许可后，按这个仓库的说明准备固件 |
| [Atheros_CSI_tool_OpenWRT_UserSpaceApp_src](https://github.com/xieyaxiongfly/Atheros_CSI_tool_OpenWRT_UserSpaceApp_src) | 路由器上运行的用户态工具，包含 sendData、recvCSI 和 MATLAB 解析目录 | 第 2 步用 sendData/recvCSI 跑官方小包测试并解析 CSI；第 3 步沿用接收记录检查自定义 sample_id（这部分需要我们自己发包，不是仓库现成功能） |

## 实验安排

1. **先核对设备和数据路径。** 对照 OpenWrt/驱动仓库记录 TX/RX 的完整型号、硬件版本、无线芯片、驱动和当前固件；同时确认机器狗数据现在走哪条无线链路、视觉/雷达具体传什么数据，以及位置从哪里来。型号或固件不清楚时先停下来核实，不试刷。

2. **先把 CSI 链路跑通。** 如果实验室已有兼容设备，就先用现成设备；TX 和 RX 之间只走 Wi-Fi，暂时不接机器狗和传感器。按用户态仓库的用法在 RX 启动 recvCSI、在 TX 用 sendData 发少量测试包，再用配套解析程序看记录里有没有有效 CSI。记录数不一定和发包数完全相同。如果设备里没有这些命令，再确认目标架构后编译；不先在 Jetson 或本机盲装驱动。

3. **验证业务数据和 CSI 的对应关系。** 官方 sendData 先用于基线测试；通过后再发带 sample_id、数据类型和时间戳的小 UDP 包，检查接收记录能否同时找到标识和有效 CSI。这个 sample_id 是我们自己的业务字段，不假设官方测试程序已经支持。优先沿用已有消息序号；一个样本可能对应多条 CSI。只有应用程序自己把样本切成多块时，才加 chunk_id。

4. **确认机器狗的数据真的经过被测 Wi-Fi。** 先从 Jetson 发小测试数据到接收端，确认数据走的是 TX 到 RX 的无线链路，同时接收端能记录到对应 CSI。如果用外接 TX，测到的是外接节点到 RX 这一段 Wi-Fi，不等于 Jetson 自带无线网卡的 CSI。

5. **再加位置和传感器数据。** 从实际使用的 odom、SLAM、TF 或外部定位取得 x、y 和时间戳；先单独接相机或雷达一路。确认样本编号、位置和 CSI 能对上后，再换另一类数据或做多位置测试。

## 数据怎么对应

优先沿用 ROS 或业务数据已有序号；没有时再增加 sample_id。一个样本可能对应多条 CSI，先确认接收记录能否读出载荷里的 sample_id，再用时间戳辅助匹配。x、y 从实际使用的 odom、SLAM、TF 或外部定位取得，并记录坐标系和来源。ROS、Jetson 和无线设备时钟可能不同，没做同步前不要把它们当成同一时间。

首轮做到两件事就够：RX 能采到有效 CSI，小 UDP 里的 sample_id 能在对应记录里找到。通过后再接机器狗数据和位置。

## 操作前注意

现在不需要为了采 CSI 去改本机 Ubuntu、Docker 或 Jetson。真实采集要靠兼容的无线设备和驱动。固件编译或刷写前，要先确认设备型号、对应镜像、备份恢复办法和实验室许可；条件不清楚就先不刷。

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
