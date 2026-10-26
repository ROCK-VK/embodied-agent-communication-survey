# CSI-centric HANDSHAKE_DIAG 离线实现与构建记录

## 状态

- 离线实现、测试和 ESP-IDF build 已完成。
- 新固件尚未烧录；当前实际 ESP 仍按最后一次确认状态运行旧的 8d-a 诊断固件。
- 本阶段未操作 Jetson、AP或 ESP Wi-Fi；未断连、重连、发 UDP。
- COM10 已通过 Windows PnP 只读确认当前存在，设备为 USB-Enhanced-SERIAL CH343；本报告记录时尚未开始烧录。

## 实现

- 新增固件模式 `HANDSHAKE_DIAG`。CSI callback 依据 Data frame 的 ToDS/FromDS、RA、TA 选择精确 Jetson↔AP 上下行，不依赖 CSI API 的 `mac` 一定是 Jetson。
- HANDSHAKE_DIAG 中 promiscuous callback 仅保留既有聚合统计，不导出 FRAME；不会再依赖 promisc↔CSI 跨回调关联。
- CSI callback 对目标 pair 统计方向、Protected/clear、长度、LLC/SNAP 与 EtherType `0x888e`。导出候选限于 clear、未分片、非 A-MSDU、API payload ≤256B、header/payload overlap 一致且为 `0x888e` 的帧。
- 一条 CSI_DATA 原子记录包含同一 CSI callback 的 `rx_ctrl`、802.11 header、API payload、`rx_seq`、CSI bytes、估计有效标志、`rx_state` 和 `first_word_invalid`。无效/缺失 CSI 的可识别 EAPOL frame 可保留在同一记录中，并由 host 标记 CSI 无效；不会从其他回调拼接。
- `wire8c.py` 严格核对 payload 完整性、指针重叠、header长度和重建长度。`wpa2_gate8c.py` 对 CSI_DATA 与既有 FRAME/RAW 使用相同 EAPOL-Key 分类，输出方向、Key Info、replay counter、record_serial、rx_seq 及同记录 CSI 有效性。旧 FRAME parser 保留。
- 新增 UART-only `capture_csi_diag.py`：PROBE sanity 最长15秒；HANDSHAKE_DIAG 必须用本地 stop-file、最大300秒；脚本不操作 Jetson/网络，不含自动重试。现场门禁复核时修正了PROBE模式ACK名称映射（固件ACK为`PROBE_CAPTURE`），并让工具依据最终设备计数强制检查channel 2、目标有效CSI、drop、写入/截断和传输错误；sanity失败以非零退出码停止。

## 离线验证

- 8d工具全套：44项通过，1项可选 tshark 集成测试跳过。
- 旧 `sniffer_8_csi` WPA2工具全套：16项通过，1项可选测试跳过。
- Python工具 `py_compile` 通过。
- 测试覆盖 CSI_DATA 重建 clear Data、LLC/SNAP、EtherType 0x888e、M1–M4分类、上下行、QoS/非QoS、header/payload overlap、畸形/截断拒绝及 Protected frame 不误判。全部为合成数据，不表示实机握手或解密成功。

## 构建

- ESP-IDF：5.5.5；Python：3.11.2；`PYTHONUTF8=1`；使用 ASCII 隔离临时目录，具体本机路径不进入公开记录。
- 配置目标：ESP32-C5；build 成功。C 编译有一条既有 UART VFS API deprecation warning，不影响构建。
- `CMakeLists.txt`、`staged.c`、`capture_core.inc`、`sdkconfig`、`sdkconfig.defaults` 的 build 副本 SHA-256 均与本地源码/配置对应文件一致。
- app：`sniffer_8d_csi_centric.bin`，909,472 bytes，SHA-256 `7AE079A2C62092D5D48EC9F485CB16FA1960703B57ADF9E60A882E56A929DDC8`。1 MiB app 分区余量约13%。

## 下一步门禁

1. 仅向 COM10 烧录该 app，并确认 esptool 写入校验成功。
2. 先做 channel 2、10–15秒被动 PROBE sanity：target CSI > 0；queue/raw/CSI drop、UART/write、truncation 与 transport/parser error 均为0。失败即 STOP，不进入握手采集。
3. sanity 通过后 ARM HANDSHAKE_DIAG。随后只允许用户现场手动断开并连回 Jetson Wi-Fi 一次；不远程 reassociate、不自动 retry、不进行第二次断连。
4. 离线用 `wire8c.py` / `wpa2_gate8c.py` 统计目标 CSI_DATA、上下行、clear pair、LLC/SNAP、0x888e 和 M1–M4；报告每条消息的 record_serial、rx_seq、方向和同记录 CSI 有效性。

尚未验证：新固件实际运行、双向 CSI_DATA 实机表现、完整 M1–M4、MIC/CCMP 完整性、WPA2 解密和 packet_id 恢复。
