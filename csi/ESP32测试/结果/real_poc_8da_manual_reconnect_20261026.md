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

## 2026-10-26 M3 锚点离线分层审计

- 原始串流只有1条 `FRAME`（record 120）；本地 parser 接受为 EAPOL-Key M3，`rejected_eapol=0`。PCAP只有1帧；tshark退出码0并识别为M3、key_info=`0x13ca`、replay counter=2。M1/M2/M4没有已识别的raw/host/PCAP/tshark记录。
- `prom_target_related_data=66`、`pair_seen=66`，但`pair_frames=1`。M3附近约1.01秒统计桶内另有3个目标相关Data callback没有逐帧raw记录；当前无法判断它们的FC、方向、Protected、长度，也不能把它们认定为M1/M2/M4。对这三条握手消息，缺失最早发生在raw导出之前，但“空口未收到”与“固件候选过滤未保留”暂不能区分；没有证据显示host parser、PCAP或tshark丢帧。
- 源码审计发现 HANDSHAKE_ONLY raw候选 gate 对未接纳帧静默返回，未计数拒绝原因。已在本地源码增加上下行、Protected/clear-small和候选过滤原因的聚合统计；不改变筛选条件或每包导出行为。CSI callback在HANDSHAKE_ONLY仍只计数、不输出CSI_DATA，目标CSI计数不能替代逐帧记录。
- 27项相关离线测试通过（1项既有可选项跳过）；IDF 5.5.5隔离本机构建通过。新 app SHA256=`FB75DA54FF19930AF38C8FE6749C1E96FBA929B0BEF8AFACDACBBDF4A23DB979`；该构建**未烧录**，仍需将其视为未部署源码候选。没有再次连接、重连或操作硬件。
- 现场地址、EAPOL字节、nonce/MIC、私有串口流和PCAP仍留本机；逐字段私有审计另存本地，不发布。
