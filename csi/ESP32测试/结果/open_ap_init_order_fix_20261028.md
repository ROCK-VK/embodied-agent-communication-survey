# Open AP Wi-Fi 初始化顺序修复

日期：2026-10-28
状态：离线源码审计、修复、Python 测试与 ESP-IDF build 已完成；未烧录、未做实机复测。

## 根因结论

首轮 `CFG_OPEN_AP` 后出现 `ESP_ERR_WIFI_NOT_STARTED (0x3002)`。原源码在 `esp_wifi_start()` 之前调用 `esp_wifi_set_band_mode(WIFI_BAND_MODE_2G_ONLY)`。ESP-IDF 5.5.5 本机 `esp_wifi.h` 对该 API 明确列出：Wi-Fi 尚未由 `esp_wifi_start()` 启动时返回 `ESP_ERR_WIFI_NOT_STARTED`。因此，按已烧录源码顺序，**第一个会返回 0x3002 的调用是 `esp_wifi_set_band_mode()`**。

首轮 UART 只留下通用错误码，没有源码行号或 API 名；本结论由烧录源码的调用顺序与 IDF 5.5.5 API 返回条件确定，尚未在新固件上运行时复核。原顺序中的 `esp_wifi_set_bandwidth()` 也位于 start 前，现一并后移。IDF 5.5.5 对 `esp_wifi_set_csi_config()` 和 `esp_wifi_set_csi()` 还要求 Wi-Fi 已启动且 promiscuous mode 已启用；原 Open AP 路径没有开启 promiscuous，这是后续会遇到的独立前置条件问题。

## 原 Open AP 初始化顺序

```text
nvs_flash_init
→ esp_netif_init
→ esp_event_loop_create_default
→ esp_netif_create_default_wifi_ap
→ esp_wifi_init
→ esp_wifi_set_storage / esp_wifi_set_country_code
→ esp_wifi_set_band_mode                  ← 尚未 start，返回条件不满足
→ 注册 AP Wi-Fi 事件
→ esp_wifi_set_mode(AP)
→ esp_wifi_set_config(AP, channel 2, OPEN)
→ esp_wifi_set_bandwidth(AP, HT20)         ← 同样在 start 前
→ esp_wifi_start
→ CSI 配置（但未启用 promiscuous）
→ 队列、UART task、UDP task
→ 过早发送 READY/UDP 状态
```

## 修复后顺序

```text
nvs_flash_init
→ esp_netif_init / default event loop / default AP netif
→ esp_wifi_init / RAM storage / country / AP event handler
→ esp_wifi_set_mode(AP)
→ esp_wifi_set_config(AP, channel 2, WIFI_AUTH_OPEN)
→ esp_wifi_start
→ esp_wifi_set_band_mode(2.4 GHz only)
→ esp_wifi_set_channel(2, no secondary channel)
→ esp_wifi_set_bandwidth(AP, HT20)
→ 读取 MAC、mode、channel、bandwidth；读回不符则失败
→ 读取 SoftAP netif 地址
→ esp_wifi_set_promiscuous(true)
→ esp_wifi_set_csi_config
→ esp_wifi_set_csi_rx_cb
→ 分配并初始化 capture queues
→ 启动 UDP receiver，等待 socket bind ready
→ 启动 UART output task
→ 发送 OPEN_AP_READY
```

`MODE OPEN_AP_POC` 只有在 `esp_wifi_set_csi(true)` 成功后才启用 RF capture 与 UDP业务接收并发送 `MODE_ACK`。CSI enable 失败时回到 STOP、关闭 UDP active 标记并报告 API 错误，不会误报 ARM 成功。Open AP 初始化失败会停止后续配置、尽力清理已启动项、锁住本次失败状态并保持 UART 命令循环运行；旧 PROBE / HANDSHAKE 模式的配置路径未重构。

## API 级诊断

初始化关键步骤通过 CS8R CONTROL 记录输出 `api`、`ok`、数值 `err`、`esp_err_to_name(err)` 与可选 `detail_code`。失败事件名为 `OPEN_AP_INIT_FAILED`；成功步骤为 `OPEN_AP_INIT`。覆盖 Wi-Fi init/start、band mode、channel、bandwidth、promiscuous、CSI config/callback/enable、readback、队列、UDP socket bind 与任务启动。错误仍保持在 framed UART 协议中，不向二进制串口流插入裸日志。Host capture 收到初始化失败时会直接报告失败 API 和错误名称。

`OPEN_AP_READY` 只在 SoftAP channel/mode/bandwidth 读回符合 channel 2 / AP / HT20、CSI callback 配置完成、UDP socket bind 成功且 UART output task 启动后发出。

## 离线验证与构建

- 完整 Python unittest：84 项运行，83 项通过、1 项跳过；包括新增 7 项 Open AP 初始化静态守卫测试。
- `python -m compileall -q tools`：通过。
- ESP-IDF 5.5.5、指定 Python 3.11 环境、`PYTHONUTF8=1`、ASCII 临时项目目录：build 成功。
- App：966,736 bytes；SHA-256：`351D50A90748D199ACF198EC52C5CCBE61401B64A05796107D4A9892A121C986`。
- 最小 app 分区：`0x100000` bytes；剩余 81,840 bytes（约 8%）。分区表配置没有修改。
- 编译器保留 1 条既有弃用警告：`esp_vfs_dev_uart_use_driver()` 建议迁移到 `uart_vfs_dev_use_driver()`。IDF 工具还提示 Python env 缺少 `idf_version.txt`，但该提示可忽略且 build 成功。

## 实机边界与下一步

- 本轮没有访问 COM10、读取串口、flash 或验证新固件运行；上一轮烧入的旧 app SHA 仍是最后一次有证据的烧录版本。
- 没有 SSH / ping Jetson，没有改其 Wi-Fi、eth0、路由、ROS/DDS 或机器狗服务；没有发送 UDP 或进行 CSI 实机测试。
- 新 app 尚未烧录，因此尚未证明设备实际执行到并成功通过修复后的 SoftAP / promiscuous / CSI 初始化。
- 后续需另行进行 ESP-only sanity，先核验逐 API 日志、`OPEN_AP_READY`、channel 2 / HT20、UDP socket ready 和无启动错误；通过后再另行通知用户讨论 Jetson 手动切换。此次任务到离线 build 为止。
