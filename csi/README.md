# CSI调研与实机验证

更新：2026-10-16。本目录为本地第三阶段公开白名单副本；现场MAC/SSID/私网地址匿名，占位符需替换，原始数据及完整项目日志留本地。

## 当前结果

- Router baseline已通过：5GHz149/C5BW20，28861条AP→ESP CSI；不重复。
- 被动来源PoC已通过：Jetson上行legacy OFDM来源/方向与独立帧metadata确认；未改Jetson网络，不是VHT80或全PHY覆盖。
- 本轮物理验证七组535条有效DataCSI，约1.11–1.45条/s，Data优先UART队列drop0；RunA碰线导致设备移动，失效对照保留，物理比较改用有效静止组。
- 运动组归一化幅度方差为相邻静止组3.43/6.13倍，停止后降低，支持动态响应/局部恢复；10cm/5cm静态遮挡区分与多轮重复性不足，完整验收尚未建立。
- 物理实验使用v4且已STOP；随后新增的sniffer-5-packet-id仅完成源码/纯构建，尚未烧录，板上版本仍为v4。mode0是12bit，26复数槽分析；尾2byte/完整载波DC映射未明，不能套常规8bit53点，不作绝对校准。

## 阅读入口

- [物理验证报告](ESP32测试/结果/c5_csi_physical_validation_20261015/CSI物理合理性验证报告.md)、[汇总](ESP32测试/结果/c5_csi_physical_validation_20261015/summary.json)、[版本](ESP32测试/结果/c5_csi_physical_validation_20261015/manifest.json)
- [ESP方案](ESP32_CSI测试方案.md)、[Pi方案](树莓派4B_Nexmon_CSI测试方案.md)、[三路线](CSI当前路线与PoC验证.md)
- [Router结果](ESP32测试/结果/c5_router_20261014/ESP32-C5_路由器CSI基线结果.md)、[被动来源结果](ESP32测试/结果/c5_sniffer_jetson_20261014_online_v3/ESP32-C5_被动监听Jetson_PoC结果.md)
- [当前固件](ESP32测试/sniffer_jetson/main/sniffer.c)、[物理采集](ESP32测试/sniffer_jetson/capture_physical.py)、[离线分析](ESP32测试/sniffer_jetson/analyze_physical.py)、[旧v3快照](ESP32测试/sniffer_jetson/版本源码/sniffer-3.c)
- [UDP packet_id与CSI关联准备](数据传输与CSI关联方案.md)、[新固件v5快照](ESP32测试/sniffer_jetson/版本源码/sniffer-5-packet-id.c)、[UDP sender/receiver](ESP32测试/sniffer_jetson/udp_probe_sender.py)、[串口采集](ESP32测试/sniffer_jetson/capture_packet_id.py)、[关联分析](ESP32测试/sniffer_jetson/analyze_packet_id.py)
- [Jetson只读报告](Jetson只读补查_2026-10-13.md)、[接口报告](Jetson网络与扩展接口只读确认_2026-10-13.md)、[更新记录](更新记录.md)、[历史归档](../归档/README.md)

## 路线与下一步

ESP32-C5 / Pi4B Nexmon CSI / AX210 PicoScenes；Pi待实机，AX210仅x86原生Linux。Atheros历史备用，FeitCSI退出。物理数据支持动态环境响应，但静态遮挡重复性不足；按用户新安排先准备小型UDP packet_id→FRAME→CSI关联。狗/Jetson关机时仅做离线工具与固件准备；目标帧Protected位仍待实测，只有未保护帧可尝试解析ID。图片/LiDAR及狗运动仍后置。

不宣称UDP=Wi-Fi帧=CSI；RF5745MHz、信道带宽与CSI条/s分别报告。Jetson网络/eth0/ROS/Mihomo/服务保持现状，本轮只有授权普通用户ping，已停止；新增SSH和COM均释放。

公开本人源码/匿名统计/安全向量/图和版本说明；密码、sdkconfig/固件、原Flash、敏感原始串口SSH日志与下载依赖不上传。

## 2026-10-16实验准备

先按[修订计划](CSI下一阶段实验计划单_修订版_2026-10-15.md)执行只读门禁，参考[VHT20能力与SSH风险核验](Jetson_VHT20可行性与SSH风险核验_2026-10-15.md)。当前仅离线源码评估：同版本驱动有运行时TX限宽候选，本机节点/生效/SSH保持待实查。首次不盲重载驱动、不改AP或eth0；20MHz上限不等于强制VHT，亦不解决Protected业务ID不可见。

## 2026-10-16只读预检更新

[实机预检结果](Jetson_VHT20只读预检结果_2026-10-16.md)：SSH成功，运行时tx_bw_mode存在、原值0x21；但Jetson当前在2.4GHz/信道2、HT关联，昨日5GHz149不能作为当前事实。未改任何设备配置。

ESP是NULL被动监听，不需连接AP/配置密码；2.4GHz对照需之后匹配信道2，不能算VHT20。继续VHT20需先在有回退管理的条件下处理Jetson回5GHz，之后才能验证运行时TX限宽。当前只读，不自动切网/写参数。

## 最新：2.4GHz HT类CSI已实测，导出质量门禁未通过

[HT/PHY对照结果](ESP32测试/结果/c5_ht_control_20261016_122842/HT_PHY对照结果.md)：复用v5/NULL、只用CFG配信道2，未烧录或改变Jetson网络。30.250秒被动sanity记录964有效HT CSI（format2/len114），746组FRAME↔CSI两侧均HT一对一。新的实证说明旁路C5并非只能得到legacy CSI。

当前背景Data下FRAME/CSI队列丢弃5570/532，按sanity门禁停止，未发主动100包UDP；不是完整低速UDP对照通过，也不能计算捕获率。先另行评估输出策略并复测，之后才回5GHz研究TX/VHT20；所有设备会话已清理。
