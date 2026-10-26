# 8d-a 候选固件被动 CSI sanity（2026-10-26）

## 结论

候选固件在 ESP32-C5 上完成一次 12 秒被动采集，ESP 固定在 channel 2。捕获到 44 条来源匹配目标 Jetson 的有效 CSI，且队列丢弃、串口写错及截断均为 0；本轮**通过目标 CSI callback sanity**。

该结果只验证目标来源 CSI callback，不代表已捕获 EAPOL/完整四次握手，也不代表业务数据已导出为 CSI_DATA 原子记录。44 个大帧候选被当前 256 B 上限过滤，CSI_DATA 记录数为 0。

## 现场状态与操作范围

- 用户报告 Jetson 已连接 2.4 GHz 网络。
- 采集前单次 5 秒只读 SSH 查询 `iw dev wlan0 link` 返回 exit 255，未获得 Jetson OS 的信道信息；没有重试。
- ESP 配置 channel 2 且读回一致。CSI 统计中出现 44 条匹配目标源地址的有效记录，证明目标源无线帧在本次 ESP channel 2 监听窗口内可见；但不等同于 Jetson OS 链路状态回读。
- 没有断开、重连、远程 reassociate、发 UDP 或修改 Jetson/AP 配置。本次只配置和停止 ESP 采集。

## 采集结果

- 固件串口版本标签：`sniffer-8d-a-full-filter`；ESP channel readback=2，`channel_readback_ok=true`。
- 采集时长：12 秒；正常收到 MODE ACK、STOP ACK 与 FINAL，最终 RF capture disabled。
- Promiscuous callback：1,136（Management 1,069、Control 0、Data 64、Misc 3）。
- CSI callback：710；目标来源 44、其他来源 666；目标 header/buffer/channel-estimate-valid/rx-state-ok/target-valid 均为 44。
- PHY 汇总：legacy 657、HT 53、VHT 0。`rx_ht` 是全局分类计数，不代表 44 条目标 CSI 都是 HT。
- CSI_DATA 导出 0；大帧过滤 44。当前候选导出上限仍为 256 B。
- 资源：queue drop 0、write errors 0、截断 0、payload missing 0、empty CSI 0；最低 free heap 109,484 B。

## 下一步门禁

1. 当前目标 CSI sanity 已通过，可准备一次 HANDSHAKE_ONLY 采集。
2. Jetson 的断开/连回必须由用户在本机手动执行；Codex 不远程重关联，不自动重试。
3. 用户确认准备后，再启动一个有时限的 ESP 监听窗口；先报告已 ARM 和状态，再由用户断开/恢复一次。若窗口异常或过期，停止并分析，不自动重开。

原始串口流保留在本地 `ESP32测试/结果/real_poc_8da_candidate_passive_sanity_20261026_174157/`，不发布原始数据、MAC/IP、凭据或构建二进制。
