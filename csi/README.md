# CSI 调研与实机验证

更新：2026-10-21。当前主线是 ESP32-C5 在 2.4 GHz HT20 下采集 CSI，并推进 packet_id ↔ Wi-Fi Data ↔ CSI。

## 当前进度

8d-a full-filter 固件已多次实机收到 Jetson 的有效 CSI。最新一次 HANDSHAKE_ONLY 采集约239秒，CSI callback 11,927 次，目标来源有效 CSI 1,309 条、HT 分类计数 3,286；队列丢弃、串口错误和截断均为0，最低空闲 heap 58,104 B。

本轮只尝试了一次远程 reassociate，命令返回 exit code 1；随后约18秒内 SSH 端口44/44可达，没有确认断网重连，也没有捕获 EAPOL 或 M1–M4。采集正常到时停止。详细匿名结果见[单次重关联尝试报告](ESP32测试/结果/real_poc_8da_single_reassociate_20261021.md)。

## 下一步

用户提出改由现场手动断开并恢复 Jetson Wi-Fi。下次先重新 ARM ESP 并确认 CSI 与 SSH 状态，再由用户手动执行一个断开/恢复周期；不自动重试。完整4-way握手通过验证前，不进入 UDP、WPA2 解密或 packet_id 实验。

## 项目边界

- 不运行含自动重连循环的旧 orchestrator。
- HANDSHAKE_ONLY 中的 CSI callback 计数不等同于 CSI_DATA 原子记录；EAPOL、M1–M4 需从真实记录离线确认。
- 8d-a 使用 full promiscuous filter；HANDSHAKE 诊断候选限于配对方向、未加密且不超过256B，EAPOL 识别路径独立。
- Jetson网络、驱动、ROS、服务、AP与传感器链路保持保护约束；没有现场授权前不主动改动网络。
- 本地保留原始串流、Protected frame、握手与逐包资料；公开仓库只放自有代码和脱敏汇总。

## 阅读入口

- [HT主方案与WPA2业务关联计划](HT主方案与WPA2业务关联计划_2026-10-16.md)
- [8d-a代码与模式说明](ESP32测试/sniffer_8d_a_full_filter/README.md)
- [8d-a接管审计](ESP32测试/结果/real_poc_8da_handoff_audit_20261019.md)
- [pair-clear修复与被动CSI sanity](ESP32测试/结果/real_poc_8da_pairclear_20261021.md)
- [更新记录](更新记录.md)

Pi4B Nexmon、AX210 PicoScenes、VHT20、ESP AP 和传感器接入均为后续阶段；Atheros保留为历史备用，FeitCSI不属于当前主路线。
