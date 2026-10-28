# Open AP 修复固件烧录与 ESP-only sanity

日期：2026-10-28 12:34（本地时间）
状态：app-only 烧录校验通过；ESP-only 启动 sanity 通过；已按任务边界停在 Jetson 切网之前。

## 烧录

- 设备：ESP32-C5 rev1.0，4 MB Flash；串口 COM10。
- 写入范围：仅 app 分区 `0x10000`，未写 bootloader、partition table、NVS。
- App 大小：966,736 bytes。
- App SHA-256：`351D50A90748D199ACF198EC52C5CCBE61401B64A05796107D4A9892A121C986`。
- esptool 对写入数据报告 hash verification 通过，随后 hard reset。
- 该 SHA 与本地 IDF 5.5.5 构建产物一致；本次设备运行版本由刚完成的串口 sanity 证据确认。

## ESP-only sanity

使用 3 Mbaud UART 限时采集 15 秒，只启动 ESP Open SoftAP 与 CSI 捕获状态；没有连接 Jetson、没有发送业务 UDP。

| 检查项 | 结果 |
|---|---|
| `OPEN_AP_READY` | 收到 |
| Open AP 初始化 API | 28 个不同 API 全部 `ESP_OK`，无初始化失败事件 |
| 模式 | `OPEN_AP_POC` ACK 收到，`rf_capture_enabled=true` |
| 信道与带宽 | 读回 channel 2 / 20 MHz，readback 通过 |
| UDP server | bind ready，错误码 0 |
| 最终停止 | 收到 `STOP` ACK 与 `FINAL` |
| station connected | 否 |
| UDP socket 收包 / CRC-valid | 0 / 0（本轮没有客户端或 probe） |
| CSI_DATA / packet_id | 0 / 0（没有关联 station，不用于判定目标 CSI 能力） |
| queue/raw/CSI drop | 0 / 0 / 0 |
| CSI/payload/raw truncation | 0 / 0 / 0 |
| UART write error | 0 |
| Host transport/parser errors | 0 |
| 最低剩余 heap | 60,872 bytes |

## 结论与边界

- **实机确认：** 修复后的初始化顺序已运行通过；此前 `ESP_ERR_WIFI_NOT_STARTED (0x3002)` 启动失败不再出现。Open SoftAP 在 channel 2 / 20 MHz 下报告 ready，CSI capture 可被 ARM，UDP socket bind 成功，限时停止和 UART framing 正常。
- **本轮未验证：** Jetson 关联、真实 STA 帧 CSI、UDP接收、CSI_DATA 中恢复 `packet_id`。由于无 station，CSI_DATA=0 是预期结果，不是目标流量测试失败。
- **网络边界：** 没有 SSH / ping / 操作 Jetson，没有切换其 Wi-Fi，没有动 eth0、ROS/DDS、Go2 或 MID360；没有发送 UDP probe。
- **下一步：** 到 Jetson 手动切换前停止。后续需另行确认并由用户现场手动把 Jetson USB Wi-Fi 切到 ESP Open AP，再执行一次受控小包 PoC；不得由固件或脚本自动改 Jetson 网络。

原始 UART stream、JSONL、时间戳文件和设备标识仅保存在本机私有目录，不随报告发布。
