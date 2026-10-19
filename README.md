# CSI调研与实机验证

更新：2026-10-19。主线HT20下packet_id↔Wi-Fi Data↔CSI。

## 最新真实实验：A类握手不完整，已停止

8c HANDSHAKE_ONLY真实ACK后，用户授权的一次Jetson正常重关联完成、SSH恢复。ESP仅捕到M1（tshark独立确认），M2/M3/M4均0；没有进入PROBE、20包或现场解密。CSI callback总数也为0，需先诊断真实RX路径。队列/传输/截断错误0、minheap102184B，非此前F类导出失败。

ESP已STOP/FINAL、COM释放、SSH退出；原WLAN/HT20/IP/route/eth0/TX0x21保持。Gate A2和端到端业务PoC未通过。8c filter与8b已验证初始化存在差异，尚未定因；下一步先仅计数RX诊断/被动CSI核验，不盲目重复断网。

## 阅读入口

- [本次真实握手结果](csi/ESP32测试/结果/c5_8c_real_wpa2_20261019_171844/8c真实握手结果.md)
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

历史协议/模拟资料见[归档](归档/README.md)。
