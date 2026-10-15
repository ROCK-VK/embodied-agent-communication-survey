# CSI调研与实机验证

更新：2026-10-15。本目录为本地第三阶段公开白名单副本；现场MAC/SSID/私网地址匿名，占位符需替换，原始数据及完整项目日志留本地。

## 当前结果

- Router baseline已通过：5GHz149/C5BW20，28861条AP→ESP CSI；不重复。
- 被动来源PoC已通过：Jetson上行legacy OFDM来源/方向与独立帧metadata确认；未改Jetson网络，不是VHT80或全PHY覆盖。
- 本轮物理验证七组535条有效DataCSI，约1.11–1.45条/s，Data优先UART队列drop0；RunA碰线导致设备移动，失效对照保留，物理比较改用有效静止组。
- 运动组归一化幅度方差为相邻静止组3.43/6.13倍，停止后降低，支持动态响应/局部恢复；10cm/5cm静态遮挡区分与多轮重复性不足，完整验收尚未建立。
- 当前工作区/板为sniffer-4-physical且STOP，旧v3快照保留。mode0是12bit，26复数槽分析；尾2byte/完整载波DC映射未明，不能套常规8bit53点，不作绝对校准。

## 阅读入口

- [物理验证报告](ESP32测试/结果/c5_csi_physical_validation_20261015/CSI物理合理性验证报告.md)、[汇总](ESP32测试/结果/c5_csi_physical_validation_20261015/summary.json)、[版本](ESP32测试/结果/c5_csi_physical_validation_20261015/manifest.json)
- [ESP方案](ESP32_CSI测试方案.md)、[Pi方案](树莓派4B_Nexmon_CSI测试方案.md)、[三路线](CSI当前路线与PoC验证.md)
- [Router结果](ESP32测试/结果/c5_router_20261014/ESP32-C5_路由器CSI基线结果.md)、[被动来源结果](ESP32测试/结果/c5_sniffer_jetson_20261014_online_v3/ESP32-C5_被动监听Jetson_PoC结果.md)
- [当前固件](ESP32测试/sniffer_jetson/main/sniffer.c)、[物理采集](ESP32测试/sniffer_jetson/capture_physical.py)、[离线分析](ESP32测试/sniffer_jetson/analyze_physical.py)、[旧v3快照](ESP32测试/sniffer_jetson/版本源码/sniffer-3.c)
- [Jetson只读报告](Jetson只读补查_2026-10-13.md)、[接口报告](Jetson网络与扩展接口只读确认_2026-10-13.md)、[更新记录](更新记录.md)、[历史归档](../归档/README.md)

## 路线与下一步

ESP32-C5 / Pi4B Nexmon CSI / AX210 PicoScenes；Pi待实机，AX210仅x86原生Linux。Atheros历史备用，FeitCSI退出。先固定ESP与线缆、复测有效物理对照，再packet_id、最后传感器与位姿；不自动进入下一阶段或ESP AP Plan B。

不宣称UDP=Wi-Fi帧=CSI；RF5745MHz、信道带宽与CSI条/s分别报告。Jetson网络/eth0/ROS/Mihomo/服务保持现状，本轮只有授权普通用户ping，已停止；新增SSH和COM均释放。

公开本人源码/匿名统计/安全向量/图和版本说明；密码、sdkconfig/固件、原Flash、敏感原始串口SSH日志与下载依赖不上传。
