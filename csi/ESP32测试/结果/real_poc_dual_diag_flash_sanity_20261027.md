# HANDSHAKE_DUAL_DIAG 候选固件烧录与 PROBE sanity

日期：2026-10-27

## 结果

- ESP32-C5 通过 Windows CH343 串口 COM10 连接。
- ESP-IDF 5.5.5 app-only 烧录成功。只写入 app 区地址 0x10000，esptool 对写入数据报告 hash verified；未写 bootloader、分区表或 NVS。
- 烧录 app SHA-256：829F6C805E4067C3D7650CD4772C2BCD5B3933E67E1CFCC4134003D82E4C5D7D，917,376 bytes。构建和写入版本对应。
- Jetson 只读 SSH 查询确认 wlan0 连接频率为 2417 MHz，对应 channel 2；本轮没有断开、重连或修改 Jetson。
- 12.14 秒 PROBE 被动 sanity：请求/读回 channel 均为 2，MODE ACK、STOP ACK、FINAL 均收到。
- CSI callback 总数 366；目标来源有效 CSI 43；CSI_DATA 记录 1。候选入队/输出各 1。
- queue_drop、raw_drop、csi_drop、write_errors、raw/csi/payload truncation 均为 0；transport/parser/CRC 类错误均为 0；sanity_failures 为空。最低 free heap 109,524 bytes。
- sanity 通过。之后还没有 ARM DUAL_DIAG，也没有手动断开 Jetson Wi-Fi。

## 当前版本边界

候选 app 已经由 esptool 写入并校验；本次采集读回到通用版本标签 sniffer-8d-csi-centric，该标签本身不含 app SHA。固件 app 内容以本次写入校验和上述候选 SHA 为依据；尚未通过芯片独立读取 app SHA 的方式复核。DUAL_DIAG 的实机行为尚未验证。

## 下一步

1. 启动最长 300 秒的 HANDSHAKE_DUAL_DIAG，确认 MODE_ACK、channel 2、目标 CSI 继续增长且错误计数为 0。
2. ESP 监听状态确认正常后，再由用户在 Jetson 本机手动断开 Wi-Fi一次；不远程重关联、不自动 retry，eth0 保持不动。
3. 观察重连窗口及之后 10–20 秒，STOP 后检查 FRAME/CSI_DATA、M1–M4、方向、200 ms timeline 和 drop/error 统计。不要在同一轮重复断连。
4. 仅在获得真实可用握手并经本机 tshark WPA2 profile 检查后，才进入 20 个 48-byte UDP 的 packet_id 关联阶段。

此报告只包含脱敏聚合结果；原始 UART stream、MAC、SSID、Protected payload、PCAP 和私有分析均留本机。