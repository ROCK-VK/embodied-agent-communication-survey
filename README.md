# 智能体与具身智能通信协议调研

**项目：基于多模态机器狗的通感算控一体化平台搭建**

本仓库整理单智能体模块接口、消息格式与数据传输机制，并进一步研究感知结果在通信/计算开销约束下的选择，以及网络通信与A2A智能体任务协作。

**最新进展（2026-10-04）：基础协议调研、两阶段本地模拟与网络/A2A研究已完成。所有实验均在电脑上运行，尚无机器狗或Jetson实物接入。**

## 阅读入口

| 想了解的内容 | 文档 |
|---|---|
| 最新结果、学长要求对应情况和结论 | [综合模拟报告](simulation/下一阶段/综合模拟报告.md) |
| 网络通信分层，A2A/gRPC/MQTT/Zenoh用途 | [网络与智能体通信调研](simulation/网络调研.md)，结合综合报告第11、12节 |
| ROS、DDS与宇树公开消息接口 | [单智能体通信协议调研报告](单智能体通信协议调研报告.md)、[实验模块接口](simulation/模块接口.md) |
| 宇树基础操作资料与Orin NX配置假设 | [宇树与Orin基础操作](simulation/下一阶段/宇树与Orin基础操作.md) |
| 代码、结果、环境与复现 | [模拟成果入口](simulation/README.md)、[发布与复现说明](simulation/发布说明.md) |
| 参考资料和证据边界 | [基础资料索引](docs/资料索引.md)、[本阶段资料索引](simulation/下一阶段/资料索引.md) |

## 任务与完成情况

最初任务是从单智能体模块接口、消息格式和数据传输入手，后续考虑多智能体通信。结合Orin NX背景、ROS1更多的反馈，以及感知数据价值选择和网络/A2A建议，本阶段完成：

| 方向 | 已完成的调研或模拟 |
|---|---|
| 感知数据选择 | 首阶段360组合成特征试验；新增480组公开图像选择/训练对照，检验字节预算、训练工作量与独立测试指标 |
| 优化边界 | 小规模可加代理目标的精确背包解与穷举一致；未证明训练效果最优 |
| ROS通信 | ROS1模块链路与异常场景；ROS2同契约和QoS兼容验证 |
| 实际本地网络 | 独立Docker容器间TCP、UDP、ROS1共7场景，验证延迟/丢包/限速、TTL与重连去重 |
| A2A任务协作 | 两个独立服务，验证发现、真实结果委派、SSE断开后查询、取消与错误、已完成任务重启恢复等11项检查 |
| 设备准备 | 阅读7篇宇树官方基础资料，整理Orin/JetPack/ROS版本假设和待实机核对步骤 |

复杂筛选策略没有稳定优于随机/间隔基线，负结果保留。A2A属于应用层任务协作，适合分析与协调；ROS/DDS负责感知数据流，IP与TCP/UDP承担网络及传输职责。A2A本身不解决最优数据选择。

## 结果与范围

最新阶段包含图表、逐次试验、配置、接收数据训练结果及24项原始本地综合审计。它们证明本地模拟机制运行，不能推断真实机器狗、Orin NX的性能或无线链路效果。

机器狗具体型号、内存、载板、JetPack、固件与真实运行版本仍未确认；Go2 EDU、NX16GB与JetPack5.1.1只是明确标注的工作假设。尚未验证原生宇树DDS/ROS1桥接、真实多模态训练、跨设备时钟与无线通信、硬件功耗或执行中任务崩溃续跑。

原2026-09-28—2026-10-04计划与执行完成情况见[首阶段工作计划](simulation/工作计划.md)和[任务回顾](simulation/任务回顾.md)；新增阶段目标与验收见[目标与计划](simulation/下一阶段/目标与计划.md)。旧“待执行”计划入口已由实际成果替代。

## 发布内容

公开调研、代码、结构化结果、图表和引用链接。日志、抓包、任务数据库、虚拟环境、缓存及本机私有配置不上传。参考文档使用链接与必要摘要，派生图像数据遵循[数据来源与许可说明](simulation/下一阶段/数据说明与许可.md)。

## 参考文献与开源资料

核验日期：2026-09-27。GitHub 核心证据固定到提交；动态官方页面以访问日为准，设备适配仍需按实际版本复核。详细证据边界见 [资料索引](docs/资料索引.md)。

- [1] [ROS 2 Humble 基本概念（官方源码）](https://github.com/ros2/ros2_documentation/blob/35b00f1f3c1ab7c14bf85e35fa895f9f580ea279/source/Concepts/Basic/About-Nodes.rst)
- [2] [Unitree ROS 2 README](https://github.com/unitreerobotics/unitree_ros2/blob/668d1ec5a05d1c38d3306bdca7d59f2ba3581a88/README.md)
- [3] [Unitree Python SDK2 README](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/README.md)
- [4] [ROS 2 msg/srv/action 定义](https://design.ros2.org/articles/legacy_interface_definition.html)
- [5] [SportModeState.msg](https://github.com/unitreerobotics/unitree_ros2/blob/668d1ec5a05d1c38d3306bdca7d59f2ba3581a88/cyclonedds_ws/src/unitree/unitree_go/msg/SportModeState.msg)
- [6] [Go2 DDS 通道源码](https://github.com/unitreerobotics/unitree_sdk2/blob/63096d0ac0c5d2dec9d6e0c22cd5233410ca2f36/include/unitree/dds_wrapper/robots/go2/go2_pub.h)
- [7] [ROS 2 Humble 中间件实现（官方源码）](https://github.com/ros2/ros2_documentation/blob/35b00f1f3c1ab7c14bf85e35fa895f9f580ea279/source/Concepts/Intermediate/About-Different-Middleware-Vendors.rst)
- [8] [ROS 2 Humble QoS（官方源码）](https://github.com/ros2/ros2_documentation/blob/35b00f1f3c1ab7c14bf85e35fa895f9f580ea279/source/Concepts/Intermediate/About-Quality-of-Service-Settings.rst)
- [9] [Python channel.py](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/unitree_sdk2py/core/channel.py)
- [10] [Zenoh ROS 2 DDS bridge README](https://github.com/eclipse-zenoh/zenoh-plugin-ros2dds/blob/d99c1b0ce24f0ec5bb238db2cf6485756fbf71e9/README.md)
- [11] [Macenski et al. 2022：作者预印本与期刊 DOI 元数据](https://arxiv.org/abs/2211.07752)
- [12] [Zhang et al. 2024：出版社摘要与书目信息](https://link.springer.com/article/10.1007/s10846-024-02187-z)
- [13] [Unitree Request.msg](https://github.com/unitreerobotics/unitree_ros2/blob/668d1ec5a05d1c38d3306bdca7d59f2ba3581a88/cyclonedds_ws/src/unitree/unitree_api/msg/Request.msg)
- [14] [Go2 Python SportClient](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/unitree_sdk2py/go2/sport/sport_client.py)
- [15] [ROS 2 SportClient 源码](https://github.com/unitreerobotics/unitree_ros2/blob/668d1ec5a05d1c38d3306bdca7d59f2ba3581a88/example/src/src/common/ros2_sport_client.cpp)
- [16] [ROS 2 话题到 DDS 名称映射](https://design.ros2.org/articles/topic_and_service_names.html)
- [17] [OMG DDSI-RTPS 2.5 标准页](https://www.omg.org/spec/DDSI-RTPS/2.5/About-DDSI-RTPS)
- [18] [ROS 2 rmw_zenoh 官方仓库](https://github.com/ros2/rmw_zenoh)
- [19] [MCP 官方介绍](https://modelcontextprotocol.io/docs/2026-07-28/getting-started/intro)
- [20] [A2A 官方介绍](https://a2a-protocol.org/latest/topics/what-is-a2a/)
- [21] [MQTT 官方介绍](https://mqtt.org/)
- [22] [gRPC 官方介绍](https://grpc.io/docs/what-is-grpc/introduction/)
