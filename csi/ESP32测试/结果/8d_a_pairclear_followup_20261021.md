# 8d-a pair-clear 安全收紧与被动 CSI 复核

日期：2026-10-21。本文只含公开代码与匿名汇总；未包含现场 SSID、MAC、IP、原始帧/CSI、EAPOL、PCAP、认证信息或固件文件。

## 修复与验证

- HANDSHAKE 诊断用的额外 pair-small 路径仅接受配对方向、Protected 位清零且长度不超过256B的候选。原有 EAPOL 识别/入队路径独立保留；Protected=0 只是一种诊断筛选条件，不等同于 EAPOL。
- 离线 WPA2 parser 要求 M4 具有 Secure Key Info 位；无法解析成 EAPOL 的 Data FRAME 仍保留在合并 PCAP，避免把其他业务帧从原始索引中丢掉。
- 离线验证：8d-a 相关20项通过；wire测试6项通过，其中1项需要外部 tshark 的可选集成测试未运行；旧 WPA2 结构测试10项通过。新增回归覆盖 Protected/长度边界、M4 Secure 位与非 EAPOL Data FRAME 的 PCAP 保留。
- ESP32-C5 / ESP-IDF 5.5.5 构建成功，烧录校验成功，设备 READY 标签为 `sniffer-8d-a-full-filter`。本轮不发布二进制或原始日志。

## 被动 CSI sanity

三窗均约10秒，ESP固定配置 channel 2、HANDSHAKE_ONLY；没有 Jetson 重关联或主动 UDP。

| 窗口 | CSI callbacks | 目标来源 CSI | 目标有效 CSI | 全局 HT 计数 | Drop / 写错 | 最低 heap |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 554 | 0 | 0 | 30 | 0 / 0 | 109420 B |
| 2 | 569 | 0 | 0 | 15 | 0 / 0 | 104320 B |
| 3 | 799 | 10 | 10 | 88 | 0 / 0 | 105828 B |

第三窗通过短时被动 CSI sanity。HT 计数为窗口全局值，不证明目标的10条 CSI 都使用 HT。三窗均无队列丢弃/串口写错/截断并正常 STOP/FINAL。没有捕获完整 M1–M4，也没有验证 pair-small 筛选对真实握手的召回。

## Jetson Wi-Fi 现场边界

早期只读快照发现 2.4 GHz 与 5 GHz 使用不同 NetworkManager 配置，自动连接设置不同：2.4 GHz 开启、5 GHz 关闭，优先级相同。NetworkManager 与 wpa_supplicant 日志显示多次本机发起的断开和 `new-activation`，但没有直接定位激活请求的客户端；60秒 D-Bus 观察没有捕获调用者。该证据不支持把现象简单解释为 AP band steering 或 5 GHz 自动连接优先级。

随后用户手动删除了此前的 5 GHz 保存配置。SSH只读确认 `wlan0` 已连接在 2417 MHz（2.4 GHz / channel 2），此前5 GHz profile UUID已不存在。这应阻止 NetworkManager再次选择那个已删除的profile；但并未查明此前 `new-activation` 的请求来源，也未枚举系统内所有其他profile。若删除后仍发生自然切换，再被动记录 D-Bus sender/PID；不主动诱发重连。

诊断期间工具没有修改 Jetson/AP 网络，也没有重关联、重启或业务数据发送。完整握手门禁通过前，不进入 PROBE、UDP 或现场解密。任何后续重关联仍需先取得明确确认且只允许一次。
