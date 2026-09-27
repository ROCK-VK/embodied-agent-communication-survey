# 智能体与具身智能通信协议调研

**项目：基于多模态机器狗的通感算控一体化平台搭建**

本仓库整理该项目的通信协议阶段调研成果，围绕单智能体内部的模块接口、消息格式和数据传输机制展开，并为后续多智能体通信研究提供基础。

## 调研背景与目标

本阶段任务：

> 调研一下智能体/具身智能的通信协议，可以先从单智能体的模块接口、消息格式和数据传输机制入手，后续考虑多智能体的通信。

结合多模态机器狗的传感、感知、规划、运动接口和状态反馈，重点回答以下问题：

| 方向 | 关注问题 |
|---|---|
| 模块接口 | 模块如何划分与协作？Topic、Service、Action 分别适合哪些交互？ |
| 消息格式 | 如何定义字段、类型、单位、时间戳、坐标系，以及厂商接口与标准消息的映射？ |
| 数据传输机制 | ROS 2、RMW、DDS/RTPS 与网络传输是什么关系？如何考虑 QoS、带宽、时延和数据新鲜度？ |
| 多智能体扩展 | 如何处理机器人身份、命名空间、跨机坐标与时间同步、信息共享和任务协作？ |

## 调研成果

**[阅读：单智能体通信协议调研报告](单智能体通信协议调研报告.md)**

报告以 ROS 2 和宇树公开接口为重点，包含候选模块架构、消息定义分析、通信层次与 QoS、官方源码调查、相关论文梳理与简要下周计划。

[资料索引与核查边界](docs/资料索引.md) 提供来源定位、固定上游提交和各项证据能支持的结论。

## 当前范围

当前成果属于文献、官方文档和公开源码调研。宇树机器狗具体型号、Jetson 配置、系统与 SDK 版本仍待确认；Go2 是源码参考案例。文中候选架构与接口为设计建议，带宽示例为教学估算，尚无实机通信或性能实测结论。

后续先确认设备和软件配置，建立真实模块接口表，再逐步开展离线验证、设备通信测试和多智能体扩展研究。

## 仓库内容

- [单智能体通信协议调研报告.md](单智能体通信协议调研报告.md)：当前主要调研成果。
- [docs/资料索引.md](docs/资料索引.md)：参考资料、版本和证据边界。

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
