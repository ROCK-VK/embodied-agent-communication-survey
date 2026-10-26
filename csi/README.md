# CSI 调研与实机验证

更新：2026-10-26。项目目标是打通 `packet_id ↔ Wi-Fi Data ↔ CSI`，后续再关联相机、LiDAR 与位姿。

## 当前结论

- **实机已确认：**ESP32-C5 在 2.4 GHz/channel 2 可稳定取得目标 CSI；曾有 1,293 条有效 CSI、1,286 条同回调 `CSI_DATA`，当时队列/串口/截断错误为 0。
- **实机已确认：**2026-10-26 HANDSHAKE_DIAG 的 25,925 条目标 pair CSI 全部被判为 Protected；因该模式只导出 clear EAPOL，产生 0 条 CSI_DATA。这是模式 gate 的结果，不能据此断言空口没有 EAPOL。
- **实机已确认：**历史 M3 由 promiscuous callback 保存为 FRAME 并被 tshark 识别；它不是 CSI_DATA，也没有证明完整 M1–M4 或 WPA2 解密。
- **离线已完成：**新增 `HANDSHAKE_DUAL_DIAG`，由 promiscuous callback 只保存目标 pair clear EAPOL，CSI callback 则把目标 pair 的有效 CSI 与 Protected/clear frame bytes 放入同一条原子 CSI_DATA。新固件已 build，但**尚未烧录**。
- **尚未验证：**DUAL_DIAG 实机是否取得 EAPOL 与 Protected CSI_DATA；完整握手、CCMP/WPA2 解密、恢复 `packet_id` 均未验证。

## 当前技术路线

```text
Path A：promiscuous → 仅目标 pair clear EAPOL → FRAME / 本地握手 PCAP
Path B：CSI callback → 目标 pair frame bytes + CSI → 同一 CSI_DATA
Path A握手材料 + Path B业务帧 → 本地WPA2解密 → packet_id ↔ 同记录CSI
```

握手材料不要求必须来自 CSI callback。Promiscuous 和 CSI callback 不做跨回调逐包 join；最终业务关联必须在同一条 CSI_DATA 内保留 frame 与 CSI。

## 下一步

1. 回到实验室后确认 Jetson 保持原网络且在 2.4 GHz/channel 2；不远程 reassociate。
2. 只有在决定采用本地新 build 时才烧录；先做 10–15 秒被动 PROBE sanity，通过后才能 ARM DUAL_DIAG。
3. DUAL_DIAG 限时运行；如需握手，只由现场人员手动完成一个 Wi-Fi 断开/恢复周期。无自动重试。
4. STOP 后离线检查 FRAME 的 M1–M4、CSI_DATA 的 Protected 数据、资源计数与时间桶；所有 PCAP、原始记录及密钥配置留本机。
5. 至少一个真实 `packet_id` 被解密恢复、与发送/接收日志一致，且其对应同一 CSI_DATA 含有效 CSI 后，才算最小 PoC 通过。

## 入口

- 项目状态与执行历史保存在本地 `日志/`，不进入公开镜像。
- [DUAL_DIAG 离线实现与构建审计](ESP32测试/结果/real_poc_dual_diag_offline_20261026.md)
- [固件与现场步骤](ESP32测试/sniffer_8d_a_full_filter/README.md)
- [HANDSHAKE_DIAG 实机结果](ESP32测试/结果/real_poc_csi_centric_handshake_diag_20261026.md)
- [CSI callback 路径审计](ESP32测试/结果/real_poc_8da_csi_callback_path_audit_20261026.md)

## 边界

- 当前本地 build 不代表已烧录；本轮没有硬件、串口、Jetson、Wi-Fi 或网络操作。
- 不改 Jetson 的 wlan0/eth0、驱动、路由、ROS/DDS、服务或机器人网络。
- 不把“一条 UDP = 一条 Wi-Fi frame = 一条 CSI”当作前提。
- 公开仓库只同步自有源码、测试和脱敏说明；原始 stream、Protected payload、PCAP、真实地址和密钥留在本机。
