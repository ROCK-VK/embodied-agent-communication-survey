# Open AP PoC 首轮 ESP-only sanity

日期：2026-10-28
状态：未通过；已停止本轮硬件测试，未连接 Jetson。

## 已确认

- COM10识别到 ESP32-C5 rev1.0；esptool只读识别到4 MB Flash。
- 将 Open AP app-only 构建写入 `0x10000`，共963,984 bytes；esptool hash verification通过。没有写bootloader、partition table或NVS。
- READY返回 `open_ap_poc=true`；串口从默认波特率切到3 Mbaud并得到确认。
- capture工具发送运行时 `CFG_OPEN_AP` 后，ESP UART出现 `ESP_ERROR_CHECK failed`，错误码 `0x3002`。没有取得 `OPEN_AP_READY`、channel/BW读回或 `MODE_ACK`；CSI/UDP统计未产生，因此这些项目状态未知，不能记作0或通过。
- 本次异常记录仅40 bytes，未包含导致错误的源码文件/行号。
- 没有 Jetson SSH/网络操作，没有切换Wi-Fi，没有发送业务UDP；没有CSI_DATA，也没有packet_id↔CSI结论。

## 诊断边界

ESP-IDF 5.5.5 将 `0x3002` 定义为 `ESP_ERR_WIFI_NOT_STARTED`。当前 `configure()` 顺序中，`esp_wifi_set_bandwidth(WIFI_IF_AP, WIFI_BW_HT20)` 位于 `esp_wifi_start()` 之前，因此这是优先审查的候选调用；由于崩溃记录缺少源码位置，尚不能据此确认具体失败API。

## 处置与下一步

- 本轮遵守首轮失败即停止：不再次reset、不重烧、不启动第二轮，也不切换Jetson。
- 先离线核对 IDF API 状态要求和 SoftAP 初始化顺序；修订后做离线测试/build，再另行安排新的 ESP-only sanity。
- 后续只有确认 `OPEN_AP_READY`、channel 2、20 MHz、UDP server ready，且固件没有启动错误后，才通知用户讨论 Jetson 手动切换。当前不具备进入 Jetson阶段的条件。

公开记录只保留上述匿名错误码和阶段结论；原始UART片段及设备标识不公开。
