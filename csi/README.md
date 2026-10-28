# CSI 调研与实机验证

更新：2026-10-28。本阶段目标是用 ESP32-C5 Open SoftAP 建立一条可控的明文 UDP → CSI_DATA 最小 PoC；本轮不再追踪 WPA2 handshake，也不再要求捕获 M1–M4。

## 当前状态

- **已离线实现：**新增独立 `OPEN_AP_POC` 模式，不覆盖原有 `PROBE`、`HANDSHAKE_DIAG`、`HANDSHAKE_DUAL_DIAG`。
- **已离线实现：**ESP32-C5 在 2.4 GHz/channel 2、HT20、无密码 SoftAP 下监听 UDP/39001；复用 48-byte CSID 协议并校验 CRC。CSI callback 为同一条 `CSI_DATA` 原子记录保存目标帧信息与 CSI。
- **已离线实现：**Jetson sender、UART capture、CSI_DATA 解码和精确 `(run_id, packet_id)` 分析工具；只有 sender log、ESP UDP CRC 事件及同条有效 CSI_DATA 三者吻合才算 PoC 成功。
- **离线测试：**完整 Python 回归运行77项，76项通过、1项跳过；新增 Open AP 专项9项全部通过，覆盖 QoS/非QoS、DS方向、CRC、重复ID、错误/截断记录和同记录CSI有效性。4个新增 Python 工具 `py_compile` 通过。
- **ESP-IDF build：**IDF 5.5.5 / Python 3.11.2 构建成功。App 963,984 bytes，SHA-256 `312238DB6B43134EF8AE2CAAE77723C07D114CC0C29AA5316CFDBCA26F3A34FA`；source partition layout 未修改。
- **首轮 ESP 实机结果未通过：**Open AP app 已 app-only 写入 `0x10000` 且 esptool校验通过；发送 `CFG_OPEN_AP` 后固件以 `ESP_ERR_WIFI_NOT_STARTED (0x3002)` 报错，未取得 SoftAP/UDP ready。具体失败API尚未从截断的启动输出确认。
- **Jetson：**本轮没有 SSH、修改网络、切网或发送 UDP。没有进入 Jetson阶段；不会自动重试。
- **仍未验证：**Jetson关联、ESP UDP接收、CSI_DATA明文packet_id恢复和最小PoC闭环。

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
- [Open AP 离线实现与构建报告](ESP32测试/结果/open_ap_poc_offline_20261027.md)
- 项目状态与执行历史保存在本地 `日志/`，不公开同步。

## 安全边界

- 不改 Jetson `eth0`、路由、DNS、ROS/DDS、服务或 Go2/MID360 网络；切换 Jetson Wi-Fi 前必须先通知用户并等待确认。
- `1 UDP packet ≠ 1 Wi-Fi frame ≠ 1 CSI`；只接受同一 CSI_DATA 中直接恢复的 `packet_id` 与有效 CSI。
- 不公开真实 SSID/PSK、MAC、现场 IP、sender/receiver私有日志、raw CSI/frame、PCAP、凭据或 Flash 镜像。
- ESP32-C5 保留为轻量 PoC 平台；正式高性能主线后续为 x86-64 Ubuntu 22.04 + PCIe/M.2 AX210 + PicoScenes。Pi4B/Nexmon 是可选对照，Atheros 仅历史参考。
