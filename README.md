# CSI调研与实机验证

更新：2026-10-16。当前主线HT20下packet_id↔Wi-Fi Data↔CSI，最新工程为sniffer-8c分阶段采集。

## 最新完成：UART与Synthetic工程验证

- 3M UART：250/280KB/s各30秒零错误，实测249.94/279.93KB/s。
- PROBE synthetic：100/s时3000候选全输出/12000大帧预过滤；200/s时6000/24000，drop/CRC/截断0。
- HANDSHAKE_ONLY synthetic：15000普通Data只计数、30EAPOL完整输出；最低heap108116B。MODE HANDSHAKE→PROBE→STOP ACK/排空通过。
- 候选API payload<=256B，在slot/大拷贝前过滤；原子段完整保留。大聚合帧中的probe可能被过滤，真实覆盖未验证。
- 25项离线回归、官方公共WPA2 fixture工具链通过。全部synthetic标记，RF capture未启用，现场Gate A2/packet_id PoC仍未证明。

当前ESP8c已MODE STOP/FINAL、COM释放，本轮结束。Jetson不在场，未SSH或抓第三方payload。到场后只读预检/回退确认→HANDSHAKE_ONLY→完整4-way→MODE PROBE→20包→Windows解密/原子CSI关联；不直接进入JPEG。

## 阅读入口

- [8c UART/Synthetic完整报告](csi/ESP32测试/结果/c5_8c_uart_synthetic_20261016_143027/8c_UART与Synthetic验证报告.md)
- [8c源码与工具](csi/ESP32测试/sniffer_8c_staged/README.md)、[独立UART benchmark](csi/ESP32测试/uart_benchmark/README.md)
- [HT/WPA2主方案](csi/HT主方案与WPA2业务关联计划_2026-10-16.md)
- [上轮F类失败](csi/ESP32测试/结果/c5_wpa2_packetid_poc_20261016_140730/WPA2_PoC第1次执行结果.md)
- [8b历史A1窗口](csi/ESP32测试/结果/c5_csi_centric8_20261016_134717/CSI_centric_GateA1_A2结果.md)
- [v7历史失败](csi/ESP32测试/结果/c5_sniffer7_raw_sanity_20261016_132154/sniffer7_GateA结果.md)
- [ESP方案](csi/ESP32_CSI测试方案.md)、[Pi方案](csi/树莓派4B_Nexmon_CSI测试方案.md)、[路线](csi/CSI当前路线与PoC验证.md)
- [更新记录](csi/更新记录.md)

历史8b零drop只限当时窗口，后来大帧负载183 drop不能掩盖；当前8c工程改善未替代真实复验。Router/legacy/HT已有实证，物理RunA碰线失效、校准未完成。Pi/Nexmon与AX210/x86/PicoScenes、VHT20/ESP AP/传感器后置，Atheros历史备用、FeitCSI退出主路线。

公开自有代码/匿名synthetic汇总；现场raw Protected/EAPOL/CSI/PCAP、凭据/Flash/Agent配置不上传。

历史协议/模拟资料见[归档](归档/README.md)。
