# 机器狗通信协议与 CSI 调研

当前 CSI 实验阶段已调整为 ESP32-C5 Open SoftAP 明文 UDP PoC：Jetson USB Wi-Fi 作为普通 STA，连接 ESP32-C5 的 2.4 GHz/channel 2/HT20 开放网络，发送带 `run_id/packet_id/CRC32` 的小 UDP probe；ESP 同时接收 UDP 并通过 CSI callback 输出带 frame/payload/CSI 的原子记录。

## 当前进度

- OPEN_AP_POC固件和host工具已经离线实现；本轮修复SoftAP初始化次序并通过全量离线测试和ESP-IDF build。
- 原因确认：IDF 5.5.5规定esp_wifi_set_band_mode()需在esp_wifi_start()后调用；旧Open AP路径在start前调用，符合首轮ESP_ERR_WIFI_NOT_STARTED (0x3002)的确定失败条件。CSI设置另要求启动后的promiscuous模式，修复已加入。
- 新候选逐API记录初始化结果；失败不会panic，OPEN_AP_READY受channel/HT20、CSI callback、UDP bind和UART task门禁控制。
- Python unittest运行84项、83项通过、1项跳过；新增7项初始化静态守卫通过，tools compileall通过。IDF 5.5.5 build成功；app 966,736 bytes，SHA-256 351D50A90748D199ACF198EC52C5CCBE61401B64A05796107D4A9892A121C986。
- 新候选尚未烧录；没有访问COM10或操作Jetson。SoftAP实机启动、Jetson关联、UDP接收和同一CSI_DATA内恢复packet_id仍待验证。
- 旧UART异常片段只有通用0x3002，没有运行时API行名；目前根因由烧录源码顺序和IDF API contract确认，仍需新固件ESP-only sanity复核。
- 最小PoC标准不变：同一CSI_DATA内存在packet_id与有效CSI，且packet_id与sender及ESP CRC-valid UDP_RX一致。不能按时间/序号猜配。

## CSI 项目入口

- [当前方案、离线验证和后续实验步骤](csi/README.md)
- [ESP32-C5 固件与 Open AP capture流程](csi/ESP32测试/sniffer_8d_a_full_filter/README.md)
- [Open AP 离线实现与构建报告](csi/ESP32测试/结果/open_ap_poc_offline_20261027.md)
- [Open AP 首轮 ESP-only sanity 结果](csi/ESP32测试/结果/open_ap_poc_esp_sanity_20261028.md)
- [Open AP 初始化顺序修复报告](csi/ESP32测试/结果/open_ap_init_order_fix_20261028.md)
- [路线调研和备选平台资料](csi/CSI当前路线与PoC验证.md)
- [历史资料归档](归档/README.md)

公开仓库仅包含自有源码、测试和脱敏报告。真实 SSID/PSK、MAC、现场IP、原始CSI/frame、PCAP、sender/receiver私有日志和凭据不上传。
