# sniffer-8d-a full promiscuous filter diagnostic

基于 sniffer-8c-staged 建立的单变量 A/B 诊断独立固件版本（ESP32-C5 / ESP-IDF 5.5.5）。

## 核心改动

1. **唯一真正影响 RF 的单变量**：
   将 8c 中的 `WIFI_PROMIS_FILTER_MASK_DATA` 改回历史 8b 使用的 full mask：
   `WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_CTRL | WIFI_PROMIS_FILTER_MASK_DATA | WIFI_PROMIS_FILTER_MASK_MISC`。
   其余 RF 时序、信道设置、动态使能/禁用逻辑、staged 架构、CSI 配置、3M UART 均与 8c 严格一致。

2. **纯观测增强（不改变 RF 行为）**：
   - 增加 Promiscuous 回调入口类别统计：`prom_cb_total`, `prom_mgmt`, `prom_ctrl`, `prom_data`, `prom_misc`。
   - 增加 CSI 回调首行入口总计数：`csi_cb_total`。
   - 增强 CSI PHY 分类与合法性统计：`csi_source_target`, `csi_source_other`, `csi_valid_channel_estimate`, `csi_rxstate_ok`, `csi_target_valid`，以及 `rx_11b`, `rx_legacy`, `rx_ht`, `rx_vht`, `rx_other`。
   - 增加 `esp_wifi_get_channel()` 与 `esp_wifi_get_mode()` 读回检查与 CONTROL 状态导出。

## 实验与验证

- **离线回归**：通过 20 项协议与 parser 回归测试，CONTROL 状态导出新增字段解析测试全部通过。
- **实机双轮被动 RF 验证（Jetson 保持原连接不触发断网）**：
  - Run 1（30.0s）：`prom_cb_total = 3,130`，`csi_cb_total = 1,544`（从 8c 的 0 彻底恢复），目标有效 CSI 128；全局 `rx_ht = 373`，未发生队列丢包或内存异常。
  - Run 2（15.0s）：`prom_cb_total = 1,487`，`csi_cb_total = 851`，目标有效 CSI 76；全局 `rx_ht = 182`。
- **结论**：在其余 8c RF 行为保持不变时，将 promiscuous filter 由 DATA-only 恢复为 full mask，是恢复 CSI callback 的关键直接支持变量。

## 2026-10-21 HANDSHAKE pair-clear 后续

- 额外 HANDSHAKE pair-small 诊断仅接受配对方向、Protected 位清零且长度不超过256B的候选；原 EAPOL 识别/入队逻辑独立保留。这是缓解 Protected 背景小帧占用队列的筛选，不把 Protected=0 当作 EAPOL 证明。
- 8d-a相关离线回归20项通过，wire测试6项通过（1项可选 tshark 集成未运行），旧 WPA2 结构测试10项通过。parser新增 M4 Secure 位检查，并将非EAPOL Data FRAME 保留在PCAP。
- ESP32-C5 / ESP-IDF 5.5.5 build与COM10烧录校验完成。约10秒被动 sanity 三窗中，第三窗有10条目标来源 CSI、10条有效；全局 HT计数88；queue/CSI/RAW drop、串口错误与截断为0，最低heap105828B。前两窗目标CSI为0；每窗波动不能单独判作固件故障。
- 没有捕获完整 M1–M4、没有主动重关联、UDP或WPA2现场解密。HANDSHAKE候选筛选在真实握手下的召回仍待验证。完整匿名汇总见[后续报告](../结果/8d_a_pairclear_followup_20261021.md)。
