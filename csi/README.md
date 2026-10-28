# CSI 调研与实机验证

更新：2026-10-28。本阶段目标是用 ESP32-C5 Open SoftAP 建立一条可控的明文 UDP → CSI_DATA 最小 PoC；本轮不再追踪 WPA2 handshake，也不再要求捕获 M1–M4。

## 当前状态

- 已离线实现独立 OPEN_AP_POC，不覆盖原有 PROBE、HANDSHAKE_DIAG、HANDSHAKE_DUAL_DIAG。
- 方案为 ESP32-C5 2.4 GHz/channel 2/HT20、WIFI_AUTH_OPEN SoftAP；UDP/39001复用48-byte CSID协议与CRC32，CSI callback将目标帧信息与CSI放在同一条CSI_DATA中。
- Host sender、UART capture、CSI_DATA解析和精确(run_id, packet_id)分析已完成；只接受同一记录直接恢复packet_id且CSI有效。
- 离线验证：完整 Python unittest 84项运行、83项通过、1项跳过；新增初始化静态守卫7项通过；tools compileall通过。
- ESP-IDF 5.5.5 / Python 3.11.2构建成功。新候选app 966,736 bytes，SHA-256 351D50A90748D199ACF198EC52C5CCBE61401B64A05796107D4A9892A121C986；1MiB app分区剩余81,840 bytes。
- 根因：IDF 5.5.5明确 esp_wifi_set_band_mode() 在 esp_wifi_start() 前会返回 ESP_ERR_WIFI_NOT_STARTED；旧Open AP路径正是在start前调用。修复后把band/channel/BW设定移到start后，并在CSI配置前启用promiscuous。旧UART未记录API名，属于源码/API契约确认，尚待新固件实机复核。
- 初始化现在逐API输出结果；失败不panic、不误报READY。只有channel 2/HT20读回、CSI callback配置、UDP bind及UART output task均ready后才发OPEN_AP_READY。
- 新候选尚未烧录。本轮没有访问COM10，没有SSH/操作Jetson、切网络或发送UDP；新固件SoftAP/CSI运行状态待下一次ESP-only sanity确认。
- 最小PoC尚未验证：Jetson关联、UDP socket接收、同一CSI_DATA恢复明文packet_id及有效CSI。

## 当前实验顺序

1. 实验室接入 ESP 后先确认固件，再决定是否 app-only 烧录；完成 ESP 自身 SoftAP/channel/BW/UDP/CSI sanity。
2. 在用户明确确认后，由用户手动将 Jetson 的 USB Wi-Fi 切到 ESP Open AP；eth0/ROS/Go2/MID360 不动。
3. Jetson 发送 20 个、每个 UDP payload 48 bytes 的 CSID probe，默认间隔 150 ms；ESP capture 工具不操作 Jetson，也不发送 UDP。
4. 停止 ESP 后离线生成 `packet_id_to_csi.csv` 和 summary。至少一个相同 `(run_id, packet_id)` 同时出现在 sender log、ESP CRC-valid UDP_RX 和一条 CSI-valid CSI_DATA 中，才可标记最小 PoC PASS。
5. 首轮失败即停止并保留证据；不自动重连、不扩大成高负载或相机/LiDAR流量。

## 关键文件

- [固件与现场流程](ESP32测试/sniffer_8d_a_full_filter/README.md)
- [Open AP capture/analyzer](ESP32测试/sniffer_8d_a_full_filter/tools/capture_open_ap_poc.py)
- [Jetson UDP sender](ESP32测试/sniffer_8d_a_full_filter/tools/send_open_ap_probe.py)
- [Open AP 离线分析](ESP32测试/sniffer_8d_a_full_filter/tools/open_ap_poc.py)
- [Open AP 首轮 ESP-only sanity 结果](ESP32测试/结果/open_ap_poc_esp_sanity_20261028.md)
- [Open AP 初始化顺序修复报告](ESP32测试/结果/open_ap_init_order_fix_20261028.md)
- [Open AP 离线实现与构建报告](ESP32测试/结果/open_ap_poc_offline_20261027.md)
- 项目状态与执行历史保存在本地 `日志/`，不公开同步。

## 安全边界

- 不改 Jetson `eth0`、路由、DNS、ROS/DDS、服务或 Go2/MID360 网络；切换 Jetson Wi-Fi 前必须先通知用户并等待确认。
- `1 UDP packet ≠ 1 Wi-Fi frame ≠ 1 CSI`；只接受同一 CSI_DATA 中直接恢复的 `packet_id` 与有效 CSI。
- 不公开真实 SSID/PSK、MAC、现场 IP、sender/receiver私有日志、raw CSI/frame、PCAP、凭据或 Flash 镜像。
- ESP32-C5 保留为轻量 PoC 平台；正式高性能主线后续为 x86-64 Ubuntu 22.04 + PCIe/M.2 AX210 + PicoScenes。Pi4B/Nexmon 是可选对照，Atheros 仅历史参考。
