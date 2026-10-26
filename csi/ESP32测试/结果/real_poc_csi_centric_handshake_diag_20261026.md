# CSI-centric HANDSHAKE_DIAG 离线实现与构建记录

## 状态

- 离线实现、测试和 ESP-IDF build 已完成；新固件已烧录并通过12秒被动 sanity。
- ESP串口READY显示运行 `sniffer-8d-csi-centric`；esptool回读校验通过。只写入app分区`0x10000`，没有写bootloader、partition table或整片flash。
- 本轮没有通过程序/SSH操作Jetson或AP；用户在Jetson本机手动完成一次Wi-Fi断开和恢复，未发UDP。
- COM10设备为USB-Enhanced-SERIAL CH343，烧录前PnP状态OK。

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

## 实机被动 sanity

- channel 2、12秒：固件版本匹配，实际信道/readback=2，`csi_target_valid=1293`，`CSI_DATA=1286`。
- queue/raw/CSI drop、write errors、raw/CSI/payload truncation均为0；parser/CRC/transport错误为0；MODE_ACK、STOP_ACK、FINAL均收到。
- 结论：新固件通过被动 sanity，可进入一次受控 HANDSHAKE_DIAG；此结果不证明 EAPOL CSI、完整握手、解密或packet_id关联。
- 私有原始采集仅留在本机；本报告不含真实MAC、SSID、IP、原始CSI/帧、握手或PCAP。

## 单次实机 HANDSHAKE_DIAG 结果

- channel 2，约272秒，用户手动断开并恢复一次；capture以本地STOP正常结束，MODE_ACK/STOP_ACK/FINAL均收到。用户报告Jetson已重新连接；未通过SSH验证。
- CSI callback=46,218；有效目标CSI=25,925；精确Jetson↔AP pair CSI=25,925，其中Jetson→AP=24,433、AP→Jetson=1,492。
- 目标pair CSI记录中Protected=25,925、clear=0；`diag_llc_snap=0`、EtherType `0x888e`=0、CSI候选入队=0、CSI_DATA=0。promiscuous统计Data=4,301、target-related=2,366，但此模式不保留逐帧FRAME，不能据此判断其是否含EAPOL。
- queue/raw/CSI drop、write error、raw/CSI/payload truncation、transport/parser错误均为0。分片/布局计数中的`diag_reject_layout=186`为全局header布局拒绝，未按target pair归属，不能解释为握手帧被该条件过滤。
- host离线解析整段捕获：CSI_DATA/FRAME=0，EAPOL-Key M1/M2/M3/M4均0，rejected EAPOL=0；未生成可分类的EAPOL帧。因此缺失发生在CSI_DATA导出之前，不能归因为host parser、PCAP或tshark。

| 消息 | 来源 | 方向 | record_serial | 同记录CSI有效 |
|---|---|---|---:|---|
| M1 | 未观测 | — | — | — |
| M2 | 未观测 | — | — | — |
| M3 | 未观测 | — | — | — |
| M4 | 未观测 | — | — | — |

- 结论边界：本次CSI callback收到的exact pair CSI全为Protected，没有clear target pair/EAPOL候选；因此未证明CSI_DATA能携带握手材料。不能据此断言M1–M4在空口完全不存在，也不能确认它们是否只在promiscuous callback出现。host解析与加密未进入实质验证。
- 本轮唯一人工断开/恢复周期已用完；不自动重试、不再断连、不发UDP。

## 下一步门禁

1. 已完成COM10 app-only烧录和回读校验。
2. 已通过channel 2、12秒被动PROBE sanity。
3. 已完成唯一一次HANDSHAKE_DIAG人工断开/恢复，且未获得CSI_DATA/EAPOL。不要在本轮重复断连或重连。
4. 后续先按本轮计数做离线决策；尚无CSI_DATA握手材料，不进入WPA2解密或packet_id UDP阶段。任何新实机断连需另行明确安排。

尚未验证：CSI callback是否会为clear EAPOL产生CSI_DATA、完整 M1–M4、MIC/CCMP完整性、WPA2解密和packet_id恢复。
