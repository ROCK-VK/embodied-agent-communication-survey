# 机器狗通信协议与 CSI 调研

当前 CSI 实验阶段已调整为 ESP32-C5 Open SoftAP 明文 UDP PoC：Jetson USB Wi-Fi 作为普通 STA，连接 ESP32-C5 的 2.4 GHz/channel 2/HT20 开放网络，发送带 `run_id/packet_id/CRC32` 的小 UDP probe；ESP 同时接收 UDP 并通过 CSI callback 输出带 frame/payload/CSI 的原子记录。

## 当前进度

- Open AP 初始化修复固件已 app-only 烧录到 `0x10000`；esptool hash verification通过，bootloader、partition table、NVS未写入。运行 app：966,736 bytes，SHA-256 `351D50A90748D199ACF198EC52C5CCBE61401B64A05796107D4A9892A121C986`。
- ESP-only 15秒 sanity 实机通过：28个不同初始化 API 全部 ESP_OK；OPEN_AP_READY、channel 2 / 20 MHz读回、CSI capture ACK、UDP server bind ready、STOP/FINAL均正常。queue/raw/CSI drop、截断、UART写错误和host transport/parser errors全为0。
- 本次没有 station 或业务UDP，所以 UDP RX=0、CSI_DATA=0；Jetson没有连接或切网。该结果确认ESP Open AP启动链路，不代表已验证Jetson业务帧CSI或packet_id关联。
- 离线回归仍为84项（83通过、1跳过），新增初始化守卫7项通过，compileall通过；ESP-IDF 5.5.5 build app hash与烧录版本一致。
- 最小PoC仍要求：同一CSI_DATA直接恢复的 `(run_id, packet_id)` 同时匹配 sender 与 ESP CRC-valid UDP_RX，且该记录含有效CSI。

## CSI 项目入口

- [当前方案、离线验证和后续实验步骤](csi/README.md)
- [ESP32-C5 固件与 Open AP capture流程](csi/ESP32测试/sniffer_8d_a_full_filter/README.md)
- [Open AP 离线实现与构建报告](csi/ESP32测试/结果/open_ap_poc_offline_20261027.md)
- [Open AP 首轮 ESP-only sanity 结果](csi/ESP32测试/结果/open_ap_poc_esp_sanity_20261028.md)
- [Open AP 初始化顺序修复报告](csi/ESP32测试/结果/open_ap_init_order_fix_20261028.md)
- [Open AP app 烧录与 ESP-only sanity 报告](csi/ESP32测试/结果/open_ap_poc_app_flash_sanity_20261028.md)
- [路线调研和备选平台资料](csi/CSI当前路线与PoC验证.md)
- [历史资料归档](归档/README.md)

公开仓库仅包含自有源码、测试和脱敏报告。真实 SSID/PSK、MAC、现场IP、原始CSI/frame、PCAP、sender/receiver私有日志和凭据不上传。
