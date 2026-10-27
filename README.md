# 机器狗通信协议与 CSI 调研

当前 CSI 实验阶段已调整为 ESP32-C5 Open SoftAP 明文 UDP PoC：Jetson USB Wi-Fi 作为普通 STA，连接 ESP32-C5 的 2.4 GHz/channel 2/HT20 开放网络，发送带 `run_id/packet_id/CRC32` 的小 UDP probe；ESP 同时接收 UDP 并通过 CSI callback 输出带 frame/payload/CSI 的原子记录。

## 当前进度

- Open AP 固件模式、Jetson sender、UART capture、CSI_DATA parser/analyzer 已完成离线实现。
- 完整 Python 回归 71 项通过；ESP-IDF 5.5.5 构建成功。
- **尚未实机验证：**该构建尚未烧录；SoftAP实际启动、Jetson连接、UDP接收和同一CSI_DATA恢复packet_id都待后续现场验证。因此当前不能称作PoC通过。
- 不再把 WPA2 handshake/M1–M4 捕获或 CCMP 解密作为本阶段前置条件。只有一条 CSI-valid CSI_DATA 同时匹配同一 `(run_id, packet_id)` 与 ESP CRC-valid UDP_RX，才算最小 PoC 成功。
- Jetson网络切换由用户现场手动完成。任何切换前先说明并等待用户明确确认；不触碰eth0、ROS/DDS、Go2/MID360网络，不自动重试。

## CSI 项目入口

- [当前方案、离线验证和后续实验步骤](csi/README.md)
- [ESP32-C5 固件与 Open AP capture流程](csi/ESP32测试/sniffer_8d_a_full_filter/README.md)
- [Open AP 离线实现与构建报告](csi/ESP32测试/结果/open_ap_poc_offline_20261027.md)
- [路线调研和备选平台资料](csi/CSI当前路线与PoC验证.md)
- [历史资料归档](归档/README.md)

公开仓库仅包含自有源码、测试和脱敏报告。真实 SSID/PSK、MAC、现场IP、原始CSI/frame、PCAP、sender/receiver私有日志和凭据不上传。
