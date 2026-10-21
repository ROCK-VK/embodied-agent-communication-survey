# CSI调研与实机验证

更新：2026-10-21。主线仍为HT20下packet_id↔Wi-Fi Data↔CSI。

## 当前状态：被动 CSI 已复核，握手仍未通过

- 8d-a full filter 已由基线双轮和10月21日短时被动 sanity 证明能收到 Jetson CSI。最新 sanity 的第三窗记录目标来源CSI 10条、目标有效CSI 10条，队列/串口错误为0；前两窗未遇到目标帧，仅说明短窗差异。
- 10月19日的握手实验未得到完整 M1–M4；最近旧轮因资源门禁停止，落盘帧与丢帧的边界见[接管审计](csi/ESP32测试/结果/real_poc_8da_handoff_audit_20261019.md)。10月21日没有重关联、业务 UDP 或解密。
- HANDSHAKE 额外 pair-small 过滤已收紧为配对方向、Protected=0且长度<=256B；明确 EAPOL 路径保持独立。离线 parser 要求 M4 Secure 位，并保留非EAPOL Data FRAME 到 PCAP。修复与被动sanity记录见[2026-10-21后续报告](csi/ESP32测试/结果/8d_a_pairclear_followup_20261021.md)。

只读网络日志显示 Jetson 的2.4 GHz与5 GHz曾使用不同 NetworkManager profile；旧快照中2.4 GHz允许自动连接、5 GHz关闭自动连接。用户后来手动删除了此前的5 GHz profile；随后只读确认 `wlan0` 已连接在 2417 MHz（channel 2），旧 profile UUID 不存在。此前切换的具体触发进程仍未知；不要简单归因于 AP band steering 或自动连接优先级。

旧 `orchestrate_real_poc.py` 含最多四次自动 reassociate，禁止运行。稳定网络后，任何重关联前仍须报告 ESP/CSI/SSH/Wi-Fi 状态并等待用户明确确认；单次最多一次，等待不超过30秒。

## 阅读入口

- [本次真实握手结果](csi/ESP32测试/结果/c5_8c_real_wpa2_20261019_171844/8c真实握手结果.md)
- [8d-a/Gemini遗留实机结果审计](csi/ESP32测试/结果/real_poc_8da_handoff_audit_20261019.md)
- [8c UART/Synthetic工程报告](csi/ESP32测试/结果/c5_8c_uart_synthetic_20261016_143027/8c_UART与Synthetic验证报告.md)
- [8c源码与工具](csi/ESP32测试/sniffer_8c_staged/README.md)、[独立UART benchmark](csi/ESP32测试/uart_benchmark/README.md)
- [HT/WPA2主方案](csi/HT主方案与WPA2业务关联计划_2026-10-16.md)
- [8b真实F类历史](csi/ESP32测试/结果/c5_wpa2_packetid_poc_20261016_140730/WPA2_PoC第1次执行结果.md)
- [8b A1历史窗口](csi/ESP32测试/结果/c5_csi_centric8_20261016_134717/CSI_centric_GateA1_A2结果.md)
- [ESP方案](csi/ESP32_CSI测试方案.md)、[Pi方案](csi/树莓派4B_Nexmon_CSI测试方案.md)、[路线](csi/CSI当前路线与PoC验证.md)
- [更新记录](csi/更新记录.md)

已完成的工程测试：3M UART 250/280KBps×30秒零错，8c synthetic 100/200候选/s、HAND只计数、模式ACK/排空及25项离线回归通过；这些不替代真实RF/握手/解密验证。256B候选上限取slot前过滤、完整原子段保留，聚合probe覆盖仍待实测。

Router/legacy/HT历史有实证；物理RunA碰线失效、校准未完成。Pi/Nexmon、AX210/x86/PicoScenes、VHT20/ESP AP/传感器后置，Atheros历史备用，FeitCSI退出主路线。

公开自有代码与匿名统计；现场raw Protected/EAPOL/CSI/PCAP、nonce/MIC/凭据/Flash/Agent规则不上传。

历史协议与模拟资料见[归档](归档/README.md)。
