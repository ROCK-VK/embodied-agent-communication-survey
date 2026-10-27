# CSI 调研与实机验证

更新：2026-10-27。项目目标是打通 packet_id ↔ Wi-Fi Data ↔ CSI，后续再关联相机、LiDAR 与位姿。

## 当前结论

- **实机已确认：**ESP32-C5 在 2.4 GHz/channel 2 可取得目标 CSI；历史被动 sanity 曾有 1,293 条有效 CSI、1,286 条同回调 CSI_DATA，drop/串口/截断错误为0。
- **实机已确认：**2026-10-26 HANDSHAKE_DIAG 将目标 pair CSI 判为 Protected，旧模式仅导出 clear EAPOL，故没有 CSI_DATA；这不证明空口没有 EAPOL。
- **实机已确认：**历史 M3 来自 promiscuous FRAME 并被 tshark 识别；它不是 CSI_DATA，也没有证明完整 M1–M4 或解密。
- **实机已完成：**2026-10-27 app-only 烧录 DUAL_DIAG 候选并通过 esptool 写入校验；PROBE sanity 目标有效 CSI=43、CSI_DATA=1、drop/transport/truncation=0。
- **实机已确认：**一次手动 Wi-Fi 断开/恢复的 DUAL_DIAG 捕获输出 641 条目标 pair CSI、80 条有效 CSI_DATA及1条 promisc EAPOL M1 FRAME；M2/M3/M4未识别。drop、截断和串口错误为0。
- **尚未验证：**完整 M1–M4、WPA2/CCMP 解密、恢复 packet_id 和 packet_id ↔ 同记录CSI。

## 当前技术路线

Path A：promiscuous → 仅目标 pair clear EAPOL → FRAME / 本地握手 PCAP
Path B：CSI callback → 目标 pair frame bytes + CSI → 同一 CSI_DATA
Path A握手材料 + Path B业务帧 → 本地WPA2解密 → packet_id ↔ 同记录CSI

握手材料不要求必须来自 CSI callback。Promiscuous 和 CSI callback 不做跨回调逐包 join；最终业务关联必须在同一条 CSI_DATA 内保留 frame 与 CSI。

## 下一步

1. 不重复本轮 Jetson 断开/恢复；不远程 reassociate。
2. 先离线审查本轮只得到一条 M1 的证据和捕获窗口；不要把缺失消息归因到某个 filter，除非有逐帧证据。
3. 当前无完整握手，因此不发 UDP、不做 WPA2 解密。后续实机采集需另行安排且只执行一个人工断开/恢复周期。
4. 获取可验证的完整 M1–M4 后，才进入受控 CSID UDP 与本机解密；至少一个 packet_id 被正确恢复，且对应同一有效 CSI_DATA，才算最小 PoC 通过。

## 入口

- 项目状态与执行历史保存在本地 `日志/`，不进入公开镜像。
- [DUAL_DIAG 离线实现与构建审计](ESP32测试/结果/real_poc_dual_diag_offline_20261026.md)
- [DUAL_DIAG 候选烧录与 PROBE sanity](ESP32测试/结果/real_poc_dual_diag_flash_sanity_20261027.md)
- [DUAL_DIAG 手动断开/恢复实机结果](ESP32测试/结果/real_poc_dual_diag_manual_reconnect_20261027.md)
- [固件与现场步骤](ESP32测试/sniffer_8d_a_full_filter/README.md)
- [HANDSHAKE_DIAG 实机结果](ESP32测试/结果/real_poc_csi_centric_handshake_diag_20261026.md)
- [CSI callback 路径审计](ESP32测试/结果/real_poc_8da_csi_callback_path_audit_20261026.md)

## 边界

- Jetson 的断开/恢复由用户在本机手动完成；Codex 未改 Wi-Fi配置、路由、驱动或服务。
- 不改 Jetson 的 wlan0/eth0、ROS/DDS、服务或机器人网络；不把“一条 UDP = 一条 Wi-Fi frame = 一条 CSI”当作前提。
- 公开仓库只同步自有源码、测试和脱敏说明；原始 stream、Protected payload、PCAP、真实地址和密钥留在本机。
