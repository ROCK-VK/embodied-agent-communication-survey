# HANDSHAKE_DUAL_DIAG 单次手动断开/恢复结果

日期：2026-10-27

## 实验范围

- ESP32-C5 使用已构建并 app-only 烧录校验的 DUAL_DIAG 候选固件；应用 SHA-256：829F6C805E4067C3D7650CD4772C2BCD5B3933E67E1CFCC4134003D82E4C5D7D。
- ESP 配置及读回信道均为 channel 2；捕获 203.172 秒，用户在 Jetson 本机完成一次 Wi-Fi 断开与恢复。Codex 未远程重关联，也未修改 Jetson 配置。
- 原始串口流及私有解析产物只保留在本机结果目录，不进入公开镜像。

## 结果

| 指标 | 结果 |
|---|---:|
| CSI callback 总数 | 7,780 |
| 目标 pair CSI | 641 |
| CSI_DATA 输出 | 80 |
| CSI_DATA 中 CSI 有效 | 80 / 80 |
| CSI_DATA payload 完整 | 80 / 80 |
| CSI_DATA Jetson→AP / AP→Jetson | 57 / 23 |
| 目标 CSI 的 Protected / clear | 641 / 0 |
| promisc 目标 pair Data | 83 |
| promisc pair Protected / clear | 82 / 1 |
| clear LLC/SNAP / EtherType 0x888e / EAPOL 候选 | 1 / 1 / 1 |
| FRAME 输出 | 1 |
| queue/raw/CSI drop、写入错误、截断、串口解析错误 | 全部 0 |
| 最低 free heap | 104,324 bytes |

CSI callback 对 641 条目标 pair CSI 中 payload 不超过 256 bytes 的 80 条输出 CSI_DATA；另外 561 条较长记录未进入当前候选输出。输出的 80 条均为 Protected，且 frame payload 与有效 CSI 同在各自 CSI_DATA 原子记录中。

promisc 唯一 clear pair 帧满足 LLC/SNAP 与 EtherType 0x888e，进入 FRAME 并由 host parser 分类为一条 AP→Jetson 的 M1。M2、M3、M4 均未识别。M1 是 FRAME，不含同记录 CSI；历史上曾捕获的 M3 属于另一轮，不计入本轮握手。

## 时间桶与一致性

- 共 1,015 个约 200 ms 时间桶；对目标 pair、方向、保护位、EAPOL候选、入队/输出及 drop 等关键字段逐项求和，均与最终累计计数一致。
- 唯一 EAPOL 候选落在 capture-relative 约 169.8–170.0 秒的桶：该桶含 2 个 promisc pair 帧（1 clear、1 Protected）及 1 条 Protected CSI_DATA 输出。它们仅在同一时间桶，不代表相互对应。
- 该时段前后目标 CSI/pair 计数先暂停增长、随后恢复；这与用户手动断开/恢复的窗口相符，但时间桶不能单独证明确切的界面操作时刻。
- 串口 transport 的 bad header、CRC、discarded bytes、serial discontinuity、metadata conflict 和 incomplete bytes 均为 0。

## 结论与边界

1. DUAL_DIAG 实机运行、双向 CSI_DATA 和受限 promisc EAPOL 导出均工作；当前未见队列或串口导出瓶颈。
2. 本轮只分类出 M1，不能组成完整 M1–M4；没有进行 WPA2/CCMP 解密，也没有发送 UDP。
3. 82 条 Protected pair 帧只计数、不入 FRAME；本轮只有 1 条 clear pair 帧，且它成功成为 EAPOL 候选并落盘。因此没有证据表明 M2/M3/M4 被后续 EAPOL gate 拒绝；只能说本次 callback 输出中没有其他 clear target pair 帧被观察/分类。
4. 641 条 CSI pair 回调均被标为 Protected；本轮握手没有以 clear EAPOL 形式出现在 CSI_DATA 中。Path A 的 M1 与 Path B 的 CSI_DATA 不是同一 record，不能据此声称握手帧已有 CSI 原子对应。
5. 本次手动断开/恢复周期已用完。不要在本轮再断开 Jetson，也不要进入 UDP/解密阶段。后续先离线审视这次 EAPOL 观测与捕获时间窗；下一次现场周期需单独安排并再次确认。

