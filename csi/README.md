# CSI调研与实机验证

## 最新：HT20业务关联与raw7离线准备（2026-10-16）

当前驱动状态已核对为HT20；wpa_cli实际WPA2-PSK、单播CCMP/组播TKIP。旧FRAME只有元数据、没有密文或握手，不能直接生成可解密pcap。独立sniffer7 binary候选已构建、9项离线测试和tshark合成PCAP/官方WPA2样本验证通过，**未烧录、未重关联、未发新UDP**；设备仍最后验证的v6c。

当前优先HT20 raw Data+EAPOL→PC离线解密→packet_id关联，暂停VHT20/5GHz/TX参数。现场实验必须等用户再次确认和安全管理回退。[正式计划](HT主方案与WPA2业务关联计划_2026-10-16.md)、[raw7源码与工具](ESP32测试/sniffer_7_raw/README.md)。


更新：2026-10-16。公开副本由本地白名单生成，现场标识匿名；原始数据/完整日志/Agent配置仅本地。

## 当前结果

- Router baseline已通过，不重复；Jetson旁路legacy Data+CSI、HT Data+HTCSI均有实机正证据，VHT20未验证。
- 最新v6c导出优化：紧凑JSON、bulk UART、TX ring16KB、事件队列64，波特率921600；CSI原始字节/无线采集配置保持。
- 30.062秒sanity：224FRAME/165有效HTCSI/165唯一HT匹配；60.015秒主动窗口：100/100 UDP、550FRAME/406HTCSI/406唯一HT匹配。两轮本地drop/解析/write error/empty/truncated均0，回调到落盘闭合。
- 100UDP是48B/5pps；CSI含背景流量，Protected CSI406/406、业务ID关联仍0；不能解释为100包各自已配CSI或无线捕获率。
- v6/v6b失败轮次完整保留，最终窗口负载低于旧高压，不承诺全部负载零丢；ARMED可用heap30164B（任务创建前），长期压力未验。
- 当前Jetson仍2.4GHz/信道2，tx_bw_mode原0x21未写；eth0/网络/ROS/Mihomo/服务未改。新增SSH/UDP receiver结束、COM释放、ESP已STOP/FINAL。
- 当前源码/build/app烧录/READY均sniffer-6c-compact-uart。旧v3/v4/v5仅对应历史数据；旧capture_packet_id用于v5，新版用capture_compact_uart。
- 物理验证RunA碰线失效；动态响应有支持，静态遮挡重复性不足。legacy106 mode0为12bit，HT114不复用其IQ解释。

## 阅读入口

- [最新HT导出与主动UDP报告](ESP32测试/结果/c5_uart_optimization_20261016_124122/HT_UART优化与主动UDP结果.md)、[汇总](ESP32测试/结果/c5_uart_optimization_20261016_124122/summary.json)、[版本](ESP32测试/结果/c5_uart_optimization_20261016_124122/manifest.json)
- [当前固件](ESP32测试/sniffer_jetson/main/sniffer.c)、[v6c采集](ESP32测试/sniffer_jetson/capture_compact_uart.py)、[导出审计](ESP32测试/sniffer_jetson/audit_compact_export.py)、[协议解析](ESP32测试/sniffer_jetson/compact_uart.py)
- [实验计划](CSI下一阶段实验计划单_修订版_2026-10-15.md)、[只读预检](Jetson_VHT20只读预检结果_2026-10-16.md)、[TX限宽与SSH风险](Jetson_VHT20可行性与SSH风险核验_2026-10-15.md)
- [旧HT拥塞结果](ESP32测试/结果/c5_ht_control_20261016_122842/HT_PHY对照结果.md)、[物理验证](ESP32测试/结果/c5_csi_physical_validation_20261015/CSI物理合理性验证报告.md)
- [ESP方案](ESP32_CSI测试方案.md)、[Pi方案](树莓派4B_Nexmon_CSI测试方案.md)、[三路线](CSI当前路线与PoC验证.md)、[关联方案](数据传输与CSI关联方案.md)
- [更新记录](更新记录.md)、[历史归档](../归档/README.md)

## 下一步与边界

当前顺序以顶部最新HT20业务关联计划为准；下列已完成结果属于v6c历史验证。VHT20/5GHz/TX参数、ESP AP和传感器暂时后置。

路线为ESP32-C5/esp-csi、Pi4B Nexmon CSI、AX210+x86 Linux/PicoScenes；Pi未部署，PicoScenes不在ARM/WSL安装。Atheros历史备用，FeitCSI退出主方案。

公开本人源码、脱敏摘要、历史安全图；密码、带凭据配置、sdkconfig、固件/Flash、raw串口/SSH/业务日志不上传。不宣称一UDP=一Wi-Fi帧=一CSI。
