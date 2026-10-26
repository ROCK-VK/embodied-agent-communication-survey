# 8d-a 候选固件单次手动断开/连回结果（2026-10-26）

## 结论

用户手动执行了一次 Jetson Wi-Fi 断开并连回。ESP 在 channel 2 的 HANDSHAKE_ONLY 监听期间维持目标 CSI；结束前只分类到一条 EAPOL-Key Message 3，M1、M2、M4 均未捕获，严格四次握手不完整。本轮因此停止；不自动重连，也不重复本次实验。

离线 PCAP 转换和 tshark 复核均识别出同一条 EAPOL-Key Message 3；tshark 返回成功。没有完整 M1–M4，因此未验证 replay/nonce/MIC 的跨消息一致性，也未执行密钥解密。CSI_DATA 原子记录为 0，业务 packet_id 关联未进行。

## 操作边界

- 监听前 ESP 固定 channel 2，配置读回成功并进入 HANDSHAKE_ONLY；初始目标有效 CSI 为正，资源计数无错误后，才通知用户在 Jetson 本机断开 Wi-Fi。
- 用户确认断开后，ESP 仍为 HANDSHAKE_ONLY、RF启用、channel 2；队列丢弃、串口错误和截断均为0。随后用户在本机连回原 2.4 GHz Wi-Fi。
- 没有 SSH 网络命令、远程 reassociate、UDP、Jetson/AP配置修改或第二次断开/连回。
- 采集最大时限300秒；用户恢复连接并完成观察后，本地发送 STOP；实际记录跨度约170.7秒，收到 STOP ACK 与 FINAL，COM10已释放。

## 匿名统计

- 固件串口标签：`sniffer-8d-a-full-filter`；ESP实际channel=2。
- CSI callback 总数 8,952；目标有效 CSI 555。
- EAPOL parser：共1条，消息分类为 M3；M1=0、M2=0、M4=0，`complete_four_way=false`。
- 独立 PCAP/tshark 复核：捕获帧可解析为 EAPOL-Key Message 3；没有其他 EAPOL-Key 消息。
- CSI_DATA 原子记录 0；RAW/FRAME传输记录1。
- queue/raw/CSI drop、write errors、截断均0；最低 free heap 50,740 B。
- 串口记录：CONTROL 3、STATS 169、FRAME 1、FINAL 1；STOP原因为本地 STOP 命令。

## 后续门禁

- 本轮的 EAPOL/M1–M4 召回未通过，不据此断言过滤修复根因，也不再重连。
- 私有 PCAP、EAPOL字节、nonce/MIC、目标/AP标识、原始串口流只留本机；不提交或发布。
- 后续先基于当前捕获做离线分析；再次实机重连必须有新的明确任务安排，仍只能现场手动单次操作，Codex不远程重关联、不自动retry。

私有原始流和 PCAP 留在本机 `ESP32测试/结果/real_poc_8da_manual_reconnect_20261026_174716/`。
