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
  - Run 1（30.0s）：`prom_cb_total = 3,130`，`csi_cb_total = 1,544`（从 8c 的 0 彻底恢复），目标有效 CSI 128，HT CSI 128，未发生队列丢包或内存异常。
  - Run 2（15.0s）：`prom_cb_total = 1,487`，`csi_cb_total = 851`，目标有效 CSI 76，HT CSI 76。
- **结论**：在其余 8c RF 行为保持不变时，将 promiscuous filter 由 DATA-only 恢复为 full mask，是恢复 CSI callback 的关键直接支持变量。
