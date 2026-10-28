# CSI 调研与实机验证

更新：2026-10-28。本阶段目标是用 ESP32-C5 Open SoftAP 建立一条可控的明文 UDP → CSI_DATA 最小 PoC；本轮不再追踪 WPA2 handshake，也不再要求捕获 M1–M4。

## 当前状态

- 当前唯一实机目标是 ESP32-C5 Open SoftAP 明文 UDP → 同记录 CSI_DATA；WPA2 handshake/M1–M4 不再是前置任务。
- OPEN_AP_POC 固件已 app-only 烧录至 `0x10000`，esptool hash 校验通过；运行 app SHA-256 `351D50A90748D199ACF198EC52C5CCBE61401B64A05796107D4A9892A121C986`，大小 966,736 bytes。bootloader、partition table、NVS 未写入。
- ESP-only 15 秒 sanity 实机通过：28 个初始化 API 全部 ESP_OK；`OPEN_AP_READY` 收到；channel 2 / 20 MHz 读回通过；CSI capture ACK 与 UDP server bind ready；限时 STOP/FINAL 正常；UART transport/parser errors、queue/raw/CSI drop、截断和写错误均为0。
- 本轮没有 station、Jetson 或 UDP probe，因此 UDP RX=0、CSI_DATA=0、packet_id恢复=0；这不代表目标业务帧 CSI 已测，也不影响 Open AP 启动 sanity 的通过结论。
- 离线验证仍为完整 Python unittest 84项运行、83通过、1跳过；新增初始化静态守卫7项通过；compileall通过。IDF 5.5.5/Python 3.11.2 build成功；1 MiB app分区尚余81,840 bytes。
- 仍待实机验证：Jetson 手动关联 Open AP；UDP sender 与 ESP socket 收包一致性；同一 CSI_DATA 直接恢复 packet_id 且 CSI 有效。PoC PASS 仍要求至少一个一致的 `(run_id, packet_id)` 同时匹配 sender、ESP CRC-valid UDP_RX、同条 CSI-valid CSI_DATA。
- 网络保护：本轮未 SSH/ping Jetson、未切 Wi-Fi、未发送业务 UDP，未动 eth0、ROS/DDS、Go2/MID360。下一阶段进入 Jetson 手动切网前必须先通知用户并等待确认；仅允许用户现场切换一次，失败后停止。
- 报告入口：[Open AP app 烧录与 ESP-only sanity](ESP32测试/结果/open_ap_poc_app_flash_sanity_20261028.md)、[初始化顺序修复](ESP32测试/结果/open_ap_init_order_fix_20261028.md)、[首轮启动失败](ESP32测试/结果/open_ap_poc_esp_sanity_20261028.md)、[离线实现与构建](ESP32测试/结果/open_ap_poc_offline_20261027.md)。
- 公开同步仅通过本地发布脚本的白名单，限制为源码与脱敏报告；真实 SSID/PSK、MAC、现场IP、私有日志、原始CSI/frame、PCAP、凭据、sdkconfig私密内容和Flash镜像不得公开。

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
