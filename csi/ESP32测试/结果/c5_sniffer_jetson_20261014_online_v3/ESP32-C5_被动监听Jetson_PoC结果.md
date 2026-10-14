# 实验2：ESP32-C5 被动监听Jetson结果（2026-10-14）

**结论：D，当前实测已取得Jetson→ESP的来源可确认CSI，包括普通上行QoS Data。** 范围仅为此次捕获到的5GHz legacy OFDM帧，不能扩展为VHT80 CSI、所有普通上行帧覆盖或业务关联成功。

## 设备、版本与保护边界

- Jetson由用户重新开机后只读核验：wlan0 MAC<JETSON_MAC>，现有小米AP/BSSID<AP_BSSID>，5745MHz/149。执行前后SSH/MAC/频率一致，新增会话均退出。
- Agent未修改Jetson Wi-Fi、SSH配置、eth0、IP/路由/DNS、ROS、Mihomo或服务；未安装包、发送机器人控制数据或接入真实传感器业务。用户中途关机/开机是外部现场操作，分别记录，不归因于ESP测试。
- ESP32-C5 v1.0/4MB、CH343/COM10、UART921600；独立sniffer_jetson/sniffer-3，IDF5.5.5；实际源码、构建、flash Hash校验和运行ELF8c193dbe3前缀对应，完整hash见manifest。
- ESP运行WIFI_MODE_NULL，不关联AP、不scan、不启AP/DHCP客户端/Ping/UDP，配置仅通过UART下发目标MAC与149。信道读取149、请求secondary NONE；接口带宽API在NULL不可用，**实际RX带宽未直接确认**，不冒称实测BW20。Jetson80MHz仍为既有高可信推断。
- [联网核验与实现说明](../../sniffer_jetson/联网核验与实现说明.md)：当前esp-csi master仍8633d67152db2808f141cc1595970aa9cf406045，实际查看源码、C5 IDF5.5.5文档、#124/#229/#265/#270及esp-idf#18493，不只依据README。

## 300秒在线run：两个层次分别统计

| 指标 | 实测 |
|---|---:|
| ARMED后观察窗口 | 300.203秒 |
| promiscuous callback总数 | 197959 |
| promiscuous目标TA帧数 | 43915 |
| 目标header Data / Management / Control | 470 / 1 / 43444 |
| CSI callback总数 | 197959 |
| CSI source MAC匹配目标 | 43915 |
| 目标CSI达到SDK valid=1、rx_state=0且buf/len非空 | 43915 |
| CSI中header TA确认的目标数据帧（callback计数） | 470 |
| 主机成功解析的目标FRAME / CSI记录 | 17651 / 25206 |
| 成功导出的来源/头部一致、长度匹配且非零目标CSI | 25206 |
| 成功导出的普通上行QoS Data FRAME / 有效CSI | 241 / 311 |
| 独立FRAME与CSI同timestamp/TA/FC/seq唯一匹配 | 241组 |
| 目标CSI来源与header TA冲突 | 0 |
| CSI空buffer / 本实现2048字节上限截断 | 0 / 0 |

总回调数、目标回调数与落盘数分列；数量相同也不作为全部帧一一对应证明。241组匹配仅为同一无线帧的元数据核对，没有读取/匹配UDP payload、sample_id或任何相机/雷达/ROS业务。

## 来源与PHY证据

- CSI API source MAC与header Address2/TA均为重新核对的Jetson MAC；对应FRAME独立记录也为相同TA，RA为现有AP。
- 普通数据记录header type2/subtype8（QoS Data），ToDS1/FromDS0，支持Jetson STA→AP发射方向；不是AP转发下行。RTS/Block Ack等控制帧分开统计，ACK/CTS无TA，不能凭其RA认定Jetson TX。
- 成功导出目标CSI全部channel149、rx_format1（该SDK11a/11g别名，在5GHz为legacy OFDM）、len106/copied106、first_word_invalid0、estimate_valid1/rx_state0。data_hex为未增益补偿的原始SDK字节，25206条buffer hash均不同，避免仅凭callback触发判成功；复数布局/子载波语义未在本阶段进一步解析。
- 数据帧CSI证据仅证明这批可解码legacy上行帧，不能声称已接收Jetson VHT80数据的80MHz CSI。未知每包TX带宽不根据关联链路规格自动填80MHz。
- NIC只读tx_packets977→240869、rx_packets1686→76582，表明前后核验及观察附近存在网络活动；这个跨度还包含烧录/准备时间，NIC包数不是802.11空口帧数，不作CSI覆盖率分母。

## 输出瓶颈与统计限制

- callback内仅计数/复制/入队，独立task输出；队列深度32、最大CSI复制2048字节。目标记录全部尝试导出，非目标FRAME/CSI约1/64抽样，背景不是全量落盘。
- 密集目标CTRL占多数，UART/文本导出已成为瓶颈：总FRAME queue drop27075、其中目标26263；CSI queue drop19610、其中目标18709。主机有1条目标FRAME JSON解析错误，原文保留；STOP附近混入日志/串行输出的具体原因未定位，不归因为无线丢包。
- 对账：43915−18709=25206条目标CSI；43915−26263−1=17651条目标FRAME。数据FRAME241/CSI311的落盘差异来自导出过程，不能将其解释为无线CSI缺失率。
- callback kind参数观测全为0，但header FC中实际出现mgmt/data/ctrl；本版prom_*_all是callback参数计数，不作为空口帧类型结论，目标类别以header解析为准。该参数差异原因尚未定位。
- 首版配置dump_ack_en=0，但仍见ACK背景CSI；这里只记录配置与实际差异，不声称已屏蔽全部ACK。未知发射源/无TA不作为Jetson来源证据。
- 当前结果满足存在性/来源PoC，不满足完整记录/吞吐/全PHY覆盖验收。下一步可优先减少控制帧输出、保留全计数并优先导出Data、或binary framing/输出队列优化；须另实测，不承诺性能。

## 无效首轮与初始化修复

- v1在NULL模式调用STA接口带宽API返回InvalidArg、ARMED前abort，属于实现初始化失败，不是A/B/C无线能力失败。删除该调用；未切换ESP为关联STA，也未改Jetson。
- v2约300秒总FRAME73987、CSI73984，目标均0；结束SSH超时，用户确认Jetson关机，关机时刻未知，因此该负结果标inconclusive，不作为“ESP无法监听Jetson”的证据。原始run及失败源码保留本地。
- 用户重新开机后复核成功才运行v3；同时修正secondary query初始值并加入背景FRAME/TA诊断。v2旧secondary非法值不作为带宽证据。

## 是否进入对照或Plan B

- A/B/C失败：本次有效在线run**不是A/B/C，而是D（受限PHY的正结果）**。初次离线零结果不计入能力判断。
- 独立20MHz普通STA对照：当前存在性目标已证明，暂不作为进入下一步的必需条件；用于未来PHY覆盖/性能/遗漏原因研究仍有价值。用户现场暂无对照设备，记待办，不改现有AP/Jetson来替代。
- ESP AP Plan B：**本轮不需要进入**；并未证伪被动路线。未来若有新需求/失败证据，先PC验证AP+普通STA+CSI，再另行设计Jetson现场管理，不通过当前wlan0 SSH切网。
- 实验1：未重复；原router结果保留。未做sample_id/相机/LiDAR/ROS业务关联。

## 收尾与文件

- 主机已发送STOP，ESP关闭CSI/prom、排空队列并输出FINAL；COM10释放且复开/关闭确认成功。当前板仍sniffer-3，采集停止，不恢复/重跑router。
- serial_raw.log、summary.json、manifest.json、flash.log保存本地；旧v2 run和首轮失败输出同样保留。
- GitHub仅发布独立源码/构建入口/核验说明、匿名报告与统计/hash；不上传SSID密码、sdkconfig、Flash/固件或敏感原始日志。
