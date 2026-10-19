# CSI调研与实机验证

更新：2026-10-19。主线HT20下packet_id↔Wi-Fi Data↔CSI。

## 最新真实实验：8d-a CSI正常，握手门禁未通过

8d-a full filter 已两次被动采到Jetson CSI。之后四轮 real_poc 均未得到完整 M1-M4；最新一轮有442条小帧落盘、508次RAW queue drop，高水位24/24后触发resource gate并安全STOP。保存帧中441条带Protected位；未落盘的508条不能逐帧定性。

没有进入 PROBE、UDP 或 WPA2 解密。最新轮 ESP 已 STOP/FINAL，但较早一轮缺少 FINAL；当前无采集进程。Jetson此刻 ping 和 SSH 均不可达，Wi-Fi状态未知。旧 orchestrator 含最多四次自动 reassociate，修正前不得再运行。

本轮只读接管核验报告：[8d-a/Gemini遗留实机结果审计](ESP32测试/结果/real_poc_8da_handoff_audit_20261019.md)。最小 `pair_small` 过滤修复与离线测试待用户确认；COM10未枚举，尚无可确认的flash条件。

## 阅读入口

- [本次真实握手结果](ESP32测试/结果/c5_8c_real_wpa2_20261019_171844/8c真实握手结果.md)
- [8d-a/Gemini遗留实机结果审计](ESP32测试/结果/real_poc_8da_handoff_audit_20261019.md)
- [8c UART/Synthetic工程报告](ESP32测试/结果/c5_8c_uart_synthetic_20261016_143027/8c_UART与Synthetic验证报告.md)
- [8c源码与工具](ESP32测试/sniffer_8c_staged/README.md)、[独立UART benchmark](ESP32测试/uart_benchmark/README.md)
- [HT/WPA2主方案](HT主方案与WPA2业务关联计划_2026-10-16.md)
- [8b真实F类历史](ESP32测试/结果/c5_wpa2_packetid_poc_20261016_140730/WPA2_PoC第1次执行结果.md)
- [8b A1历史窗口](ESP32测试/结果/c5_csi_centric8_20261016_134717/CSI_centric_GateA1_A2结果.md)
- [ESP方案](ESP32_CSI测试方案.md)、[Pi方案](树莓派4B_Nexmon_CSI测试方案.md)、[路线](CSI当前路线与PoC验证.md)
- [更新记录](更新记录.md)

已完成的工程测试：3M UART 250/280KBps×30秒零错，8c synthetic 100/200候选/s、HAND只计数、模式ACK/排空及25项离线回归通过；这些不替代真实RF/握手/解密验证。256B候选上限取slot前过滤、完整原子段保留，聚合probe覆盖仍待实测。

Router/legacy/HT历史有实证；物理RunA碰线失效、校准未完成。Pi/Nexmon、AX210/x86/PicoScenes、VHT20/ESP AP/传感器后置，Atheros历史备用，FeitCSI退出主路线。

公开自有代码与匿名统计；现场raw Protected/EAPOL/CSI/PCAP、nonce/MIC/凭据/Flash/Agent规则不上传。
