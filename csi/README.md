# CSI 调研与实机验证

更新：2026-10-26。项目目标是打通 `packet_id ↔ Wi-Fi Data ↔ CSI`，后续再关联相机、LiDAR 与位姿。

## 当前结论

- **实机已确认：**ESP32-C5 在 2.4 GHz/channel 2 可稳定取得目标 CSI；曾有 1,293 条有效 CSI、1,286 条同回调 `CSI_DATA`，当时队列/串口/截断错误为 0。
- **实机已确认：**2026-10-26 HANDSHAKE_DIAG 的 25,925 条目标 pair CSI 全部被判为 Protected；因该模式只导出 clear EAPOL，产生 0 条 CSI_DATA。这是模式 gate 的结果，不能据此断言空口没有 EAPOL。
- **实机已确认：**历史 M3 由 promiscuous callback 保存为 FRAME 并被 tshark 识别；它不是 CSI_DATA，也没有证明完整 M1–M4 或 WPA2 解密。
- **实机已完成：**2026-10-27 app-only 烧录 HANDSHAKE_DUAL_DIAG 候选并通过 esptool 写入校验；12.14 秒 PROBE sanity 读回 channel 2，目标有效 CSI 43、CSI_DATA 1，drop/transport/truncation 为 0。
- **尚未验证：**DUAL_DIAG 实机是否取得 EAPOL 与 Protected CSI_DATA；完整握手、CCMP/WPA2 解密、恢复 `packet_id` 均未验证。

## 当前技术路线

```text
Path A：promiscuous → 仅目标 pair clear EAPOL → FRAME / 本地握手 PCAP
Path B：CSI callback → 目标 pair frame bytes + CSI → 同一 CSI_DATA
Path A握手材料 + Path B业务帧 → 本地WPA2解密 → packet_id ↔ 同记录CSI
```

握手材料不要求必须来自 CSI callback。Promiscuous 和 CSI callback 不做跨回调逐包 join；最终业务关联必须在同一条 CSI_DATA 内保留 frame 与 CSI。

## 下一步

1. Jetson 只读 SSH 已确认 2.4 GHz/channel 2；运行前只读复核即可，不远程 reassociate。
2. 当前候选 app 已烧录且 PROBE sanity 通过；下一步 ARM 限时 DUAL_DIAG。
3. 只有 ESP 确认监听正常后，才由用户在 Jetson 本机手动完成唯一一次 Wi-Fi 断开/恢复周期。无自动重试。
4. STOP 后离线检查 FRAME 的 M1–M4、CSI_DATA 的 Protected 数据、资源计数与时间桶；所有 PCAP、原始记录及密钥配置留本机。
5. 至少一个真实 `packet_id` 被解密恢复、与发送/接收日志一致，且其对应同一 CSI_DATA 含有效 CSI 后，才算最小 PoC 通过。

## 入口

- 项目状态与执行历史保存在本地 `日志/`，不进入公开镜像。
- [DUAL_DIAG 离线实现与构建审计](ESP32测试/结果/real_poc_dual_diag_offline_20261026.md)
- [DUAL_DIAG 候选烧录与 PROBE sanity](ESP32测试/结果/real_poc_dual_diag_flash_sanity_20261027.md)
- [固件与现场步骤](ESP32测试/sniffer_8d_a_full_filter/README.md)
- [HANDSHAKE_DIAG 实机结果](ESP32测试/结果/real_poc_csi_centric_handshake_diag_20261026.md)
- [CSI callback 路径审计](ESP32测试/结果/real_poc_8da_csi_callback_path_audit_20261026.md)

## 边界

- 当前候选 app 写入由 esptool 校验通过；本轮没有改变 Jetson Wi-Fi/网络，也尚未手动断开/恢复。
- 不改 Jetson 的 wlan0/eth0、驱动、路由、ROS/DDS、服务或机器人网络。
- 不把“一条 UDP = 一条 Wi-Fi frame = 一条 CSI”当作前提。
- 公开仓库只同步自有源码、测试和脱敏说明；原始 stream、Protected payload、PCAP、真实地址和密钥留在本机。
