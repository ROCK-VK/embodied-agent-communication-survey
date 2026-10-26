# CSI callback 与 promiscuous 路径源码/历史捕获审计（2026-10-26）

## 结论

- 上一轮唯一真实 M3 来自 promiscuous callback 导出的 `FRAME`（`record_serial=120`）；该串流有1条FRAME、0条CSI_DATA。M3不是由 `wifi_csi_info_t.hdr/payload` 导出。
- ESP-IDF 5.5.5 的 `wifi_csi_info_t` 包含source/destination MAC、Wi-Fi header、payload指针和长度、`rx_seq`。CSI callback原子记录从API层面能够携带frame bytes与CSI，不要求之后跨两个回调猜测配对。
- 当前453条有效目标CSI未导出逐帧hdr/payload是HANDSHAKE_ONLY模式提前return造成的；API不是没有这些字段。header已读取并经过当前目标上行地址检查，但HANDSHAKE_ONLY没有检查payload有效性/长度，因此该批capture未测出payload的逐条可用性。
- 建议将CSI-centric atomic record作为 `packet_id ↔ frame ↔ CSI` 主线；放弃“promiscuous必须承担所有Data与完整4-way并与CSI配对”的架构门槛。Protected业务的密钥获取、解密和真实packet_id恢复仍未完成。

## 证据

### M3来源

历史capture离线解码：`record_serial=120`、`event=FRAME`、PCAP frame 1；FRAME=1、CSI_DATA=0，host仅将该FRAME解析为M3。固件 `prom_cb()` 从 `wifi_promiscuous_pkt_t.payload` 复制为RAW事件；host将RAW事件命名为FRAME。该来源判断有原始串流索引和当前源码双重支持。

### ESP-IDF 5.5.5 CSI API

本机IDF checkout tag为`v5.5.5`。`wifi_csi_info_t`定义包含：

- `mac` / `dmac`：CSI帧source / destination MAC；
- `hdr`：Wi-Fi packet header；
- `payload` / `payload_len`：Wi-Fi packet payload及长度；
- `rx_seq`：该Wi-Fi packet的接收序号；
- 另有`rx_ctrl`、CSI `buf` / `len`、`first_word_invalid`。

IDF callback说明指出传入CSI data指针在回调返回后释放。因此回调内要立即复制；当前PROBE路径在callback内复制header、payload和CSI到同一atomic event，符合这一生命周期要求。

### 当前回调实现与HANDSHAKE_ONLY结果

- `csi_cb()`先要求source MAC为Jetson，并校验header addr1为AP、addr2为Jetson。它没有采用`dmac`筛选AP下行；AP→Jetson的地址排列（包含M1/M3候选）会在source筛选处提前返回。
- header检查及CSI有效性通过后，`MODE_HANDSHAKE`只增加计数并立即return；payload非空/长度检查和CSI_DATA入队只在后续PROBE分支执行。因此453条target valid CSI没有逐帧输出是模式策略导致，且这轮未测到其payload指针和长度。
- 12秒sanity历史串流中确有1条实机Protected `CSI_DATA`：API payload长度97，复制97；CSI长度114，复制114；未截断。`hdr_len=26`、`payload_minus_hdr=24`表示header与payload API区间重叠2字节；host用`assemble_api_parts()`验证重叠后还原121字节MPDU。该sample的CCMP ExtIV标志位可见，但没有验证MIC、WPA2解密或业务数据。
- `wpa2_gate8c.py`会重建CSI_DATA并把它写进PCAP；当前EAPOL-Key分类仅在FRAME/RAW分支调用。若改由CSI_DATA提供M1–M4，host parser还需处理atomic record的重建帧。

## Path A / Path B能力判断

| 目标 | CSI callback字段/API能力 | 当前实现或验证状态 |
|---|---|---|
| 识别clear EAPOL | header + payload可组合后检查802.11 header、LLC/SNAP、EtherType `0x888e` | 仍未证明CSI callback实际输出过EAPOL；host的CSI_DATA分支也尚未调用EAPOL-Key parser |
| 判定Jetson↔AP方向 | `hdr`含FC与802.11地址，`mac/dmac`可作交叉核对；可按ToDS/FromDS和地址位判方向 | 当前callback只保留Jetson source、AP receiver的上行排列；AP下行未纳入 |
| 解密Protected业务帧 | header+payload结构允许尝试重建Protected MPDU；已有1条实机Protected CSI_DATA样本完整按API长度复制 | 未验证该API payload在所有目标帧上都包含完整CCMP头、密文和MIC；没有完成WPA2解密 |
| 同一record内恢复packet_id并关联CSI | CSI_DATA在一个事件内保存header、payload、CSI及RX metadata，原子关联成立 | 尚无业务UDP `packet_id` 经解密后恢复并与同条CSI_DATA闭环的实机结果 |

## 路线建议与边界

Path B应成为业务Data ↔ CSI的主路径；其价值是同一CSI callback直接给出帧字段和CSI，避免跨promiscuous/CSI callback进行逐帧join。promiscuous callback可暂作聚合诊断计数或CSI路径故障时的有限fallback，不再要求它全量抓包并负责数据配对。

如后续仍需取得WPA2 handshake key材料，优先评估低流量的CSI callback `HANDSHAKE_DIAG`：按Jetson/AP精确pair、双向解析header，只记录可识别EAPOL的短帧及相应CSI/RX metadata；需显式统计payload缺失、长度、CSI有效性和各方向记录数。先修正当前source-only方向门控，并让host从CSI_DATA分支解析EAPOL。只有实机证明M1/M2/M3/M4在CSI callback可见且受保护业务MPDU可解密，才宣布该闭环成立。

本报告仅为源码与历史串流离线审计；未修改筛选逻辑、未build/flash、未操作Jetson或网络。公开版本不含原始串流、PCAP、payload bytes、MAC/IP或密钥。
