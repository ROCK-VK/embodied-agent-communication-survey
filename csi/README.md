# CSI调研与实机验证

> **最新实机：F类资源门禁停止。** 用户已确认回退，但重关联命令发送前ESP出现357有效callback/174落盘/drop183，自动STOP/FINAL；未重关联、发20包或现场解密。8b原30秒零drop只适用于历史窗口；先处理大帧/突发导出，不进入JPEG。[本次结果](ESP32测试/结果/c5_wpa2_packetid_poc_20261016_140730/WPA2_PoC第1次执行结果.md)。


> **此前准备（历史）：** 已完成WPA2最小PoC只读门禁与离线A2审计；13条显示差异对应Wireshark TKIP启发式，tag仍未认证。工具准备/16项离线回归通过；尚未重关联/发20包/现场解密，等待用户明确确认现场回退。[执行前审计](ESP32测试/结果/c5_wpa2_packetid_poc_20261016_140730/WPA2_PoC执行前审计.md)。


更新：2026-10-16。当前主线是HT20下业务packet_id与CSI关联，最新采用CSI-centric同回调记录。

## 历史30秒窗口：Gate A1通过，A2尚未证明

当前板`sniffer-8b-csi-centric`已STOP/FINAL，串口关闭，新增SSH退出；Jetson/AP/网络/驱动/服务未修改。30秒背景窗口3913有效目标CSI callback=3913原子记录，queue drop0，串口CRC/序号/截断错误0，最低free heap65060B。

CSI callback同时复制header、payload和CSI，避免v7跨回调严格join；promiscuous只导出可识别目标pair EAPOL。26B QoS头与payload重叠2B，按指针差与字节一致性重组候选PCAP。3900/3913记录被tshark识别CCMP，authentication tag完整性仍无独立证据，不等于已证明缺失。

当前停止于A2：不进入重关联、主动握手、新UDP或现场解密。先离线核验完整帧体/尾界，再决定下一实验。不能把SDK原生关联、标准工具识别或历史100/100 UDP描述为packet_id已关联。

## 阅读入口

- [CSI-centric结果报告](ESP32测试/结果/c5_csi_centric8_20261016_134717/CSI_centric_GateA1_A2结果.md)
- [sniffer8源码与协议](ESP32测试/sniffer_8_csi/README.md)
- [当前HT/WPA2计划](HT主方案与WPA2业务关联计划_2026-10-16.md)
- [v7历史失败报告](ESP32测试/结果/c5_sniffer7_raw_sanity_20261016_132154/sniffer7_GateA结果.md)
- [v6c HT导出与UDP历史结果](ESP32测试/结果/c5_uart_optimization_20261016_124122/HT_UART优化与主动UDP结果.md)
- [ESP方案](ESP32_CSI测试方案.md)、[Pi方案](树莓派4B_Nexmon_CSI测试方案.md)、[路线](CSI当前路线与PoC验证.md)
- [更新记录](更新记录.md)

Router baseline和legacy/HT CSI已有实证，不重复。v7池扩大仍drop/跨回调join0/最低heap12B，为历史失败；v8首版drop142/min7520B也未过，最终8b仅当前窗口通过。物理RunA碰线失效，动态响应有支持，静态遮挡重复性不足。

ESP32-C5当前实机；Pi4B/Nexmon及AX210+x86 Linux/PicoScenes后置，Atheros历史备用、FeitCSI退出主路线。VHT20/5GHz/TX调整、ESP AP和传感器后置；禁止一UDP=一帧=一CSI。原始Protected/EAPOL/PCAP/凭据/Flash/Agent配置不公开。
