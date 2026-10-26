# 8d-a 诊断计数固件：HANDSHAKE_ONLY 筛选漏斗（2026-10-26）

## 结论

诊断固件在用户现场手动断开并连回一次期间保持 channel 2 监听。目标 CSI 正常，但本轮没有 raw FRAME/EAPOL 记录，host parser未分类到 M1/M2/M3/M4。新计数表明本轮见到的63个目标相关Data callback全是Protected帧，并在候选gate的Protected分支被拒绝；这能解释这些callback未入raw，但不能证明它们中包含M1/M2/M4。没有证据支持修改EAPOL parser、PCAP转换或放宽过滤条件。

## 固件与采集

- 设备：ESP32-C5；IDF 5.5.5；诊断app SHA256 F6AD6F647F609D5B7A6BDA661B345CC471BCD9F1E5BE76569AD46B141ACCD43D，大小906,976 B；烧录时bootloader、partition table、app均由esptool校验成功。
- 捕获：HANDSHAKE_ONLY，目标channel 2读回一致；单个限时窗口，实际约149.15秒。Jetson Wi-Fi由用户现场手动断开并连回各一次；没有远程SSH网络控制、reassociate、重试、UDP或AP/Jetson配置变更。
- 收尾：本地发送一次MODE STOP，收到STOP ACK与FINAL，stop_reason=local_stop_command，串口正常关闭。

## 筛选漏斗

| 阶段 | 数量 | 说明 |
|---|---:|---|
| promiscuous Data callback | 658 | 全部Data回调 |
| target-related Data | 63 | Data header有效且TA或RA匹配目标STA |
| 精确STA↔AP pair | 63 | 上行59、下行4 |
| Protected / unprotected | 63 / 0 | 所有精确pair均为Protected |
| pair长度 <=256 B / >256 B | 61 / 2 | 长度分桶覆盖Protected与clear帧 |
| pair_small accepted | 0 | 原有条件要求精确pair、clear、<=256 B |
| clear LLC/SNAP candidate | 0 | 仅对可检查的clear Data统计 |
| EtherType 0x888e candidate | 0 | 同上 |
| candidate reject: Protected / oversize / pair mismatch / other | 63 / 0 / 0 / 0 | 63个target-related帧均命中Protected拒绝分支 |
| raw_enqueued / raw_output / raw_drop | 0 / 0 / 0 | 没有候选入队，也没有队列丢弃 |
| host EAPOL-Key M1 / M2 / M3 / M4 | 0 / 0 / 0 / 0 | 没有FRAME输入，parser没有消息可分类 |

## CSI、资源与传输

- prom_cb_total=14,751；csi_cb_total=6,128；目标有效CSI=453。
- queue_drop/raw_drop/csi_drop、write_errors、raw/csi/payload truncation、payload_missing、csi_empty均为0；最低free heap=109,336 B。
- 串流事件：CONTROL=3、STATS=147、FINAL=1；没有FRAME或CSI_DATA。UART记录/解码无错误。

## 解释与后续

本轮数量最先明显下降在 target-related Data（658→63）。对这63个目标相关帧，63个均与配置AP构成精确pair，且全部Protected；随后保护位条件使clear/pair_small候选为0，故没有可供LLC/SNAP、0x888e或M1–M4解析的raw数据。两条大于256 B的pair同样是Protected，优先计入Protected拒绝分支，不计作oversize拒绝。
这只说明本轮实际到达promiscuous callback的63条相关Data被Protected条件过滤。它不证明M1/M2/M4曾到达回调；握手EAPOL帧可能没有出现在本次可见回调中，具体原因未确认。因此不修改筛选、EAPOL parser或PCAP/tshark，也不再做第二次断开/恢复。
CSI callback采到的453条目标有效CSI未作为本模式CSI_DATA原子记录导出；本轮没有进行业务数据关联。完整握手和packet_id↔CSI仍未验证。

私有原始stream、时间戳与运行状态保存在本地结果目录；没有发布MAC、私网IP、原始帧、PCAP或凭据。
