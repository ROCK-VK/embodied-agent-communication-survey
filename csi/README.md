# CSI调研与实机验证

更新：2026-10-16。当前主线是HT20下业务packet_id↔FRAME↔CSI关联，VHT20/5GHz/TX参数及传感器后置。

## 最新Gate A：未通过并停止

- 当前已烧录/READY版本为sniffer-7b-raw-snapshot；设备已STOP/FINAL，COM释放，新增SSH退出。Jetson仍信道2/驱动HT20、原MAC/IP/route/TX参数，网络/驱动/服务/AP未改。
- 最终30.025601秒：目标上行RAW callback1611，入队/输出/host1462，queue drop149；有效目标CSI callback2676，入队/输出/host2634，drop42。
- UART写错误、binary CRC/序号/resync/半record/头部冲突、empty/truncation均0；计数可闭合，但完整Gate未过。
- 真实PCAP可生成，1458/1460 Protected行由tshark识别CCMP；严格timestamp+TA+FC+seq_ctrl匹配0、raw dump/sig尾长解释未确认，不能声称完整MPDU/MIC已验证或业务ID已关联。
- v7a首轮RAW437/436/drop1、CSI2600全落盘；v7b入口快照/池扩大未解决关联和队列问题。不要盲扩pool，最新历史最低heap12B。
- 本轮没有主动UDP、重关联、主动握手或现场解密。自然出现EAPOL只保留本地，不代表完整4-way。下一步先离线诊断，等待用户确认修正版Gate A。

## 已完成历史与边界

Router baseline、Jetson旁路legacy/HT CSI有实证。v6c元数据+CSI窗口曾零drop且UDP100/100、406HT唯一配对；它不等于新raw方案也能匹配。物理实验RunA碰线失效，动态响应有支持，静态遮挡重复性不足；不声称完整校准。

当前安全方式上次只读为WPA2-PSK/单播CCMP/组播TKIP；旧v5/v6c缺raw密文/EAPOL，不能解密。Wireshark4.6.9工具链和官方WPA2样本仅离线验证过，未现场解密。

## 阅读入口

- [Gate A实机失败报告](ESP32测试/结果/c5_sniffer7_raw_sanity_20261016_132154/sniffer7_GateA结果.md)
- [当前HT主方案与WPA2计划](HT主方案与WPA2业务关联计划_2026-10-16.md)
- [raw7源码与工具](ESP32测试/sniffer_7_raw/README.md)
- [v6c HT导出与UDP历史结果](ESP32测试/结果/c5_uart_optimization_20261016_124122/HT_UART优化与主动UDP结果.md)
- [ESP方案](ESP32_CSI测试方案.md)、[Pi方案](树莓派4B_Nexmon_CSI测试方案.md)、[路线](CSI当前路线与PoC验证.md)
- [更新记录](更新记录.md)

ESP32-C5/esp-csi当前实机，Pi4B/Nexmon和AX210+x86 Linux/PicoScenes后置；Atheros历史备用、FeitCSI退出主路线。禁止一UDP=一帧=一CSI假设。发布自有代码和匿名统计，raw Protected/EAPOL/PCAP/PSK/原Flash/Agent配置仅本地。
