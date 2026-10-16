# sniffer-8c：3M UART、分阶段采集与Synthetic工程验证

日期：2026-10-16。Windows+COM10/CH343+ESP32-C5；机器狗/Jetson不在现场。**全程未SSH Jetson、未配置真实无线目标、未采周围设备payload、未做现场握手/解密/业务ID关联。** synthetic记录带flag16，RF capture始终false。

## 已完成实测

| UART-only benchmark | 250000 B/s目标 | 280000 B/s目标 |
|---|---:|---:|
| requested baud |3000000|3000000|
| uart_get_baudrate |3004694|3004694|
| host elapsed（s） |30.006554|30.006978|
| expected / received |7324 / 7324|8203 / 8203|
| 数据wire吞吐（B/s） |249937.93|279930.63|
| gap/duplicate/CRC/malformed/resync/pattern/host loss |全部0|全部0|
| min free heap（B） |300328|300328|

独立benchmark固件不初始化Wi-Fi。UB8C header16B（magic/version/kind/header_len/serial/payload_len）+确定性payload1004B+CRC32 4B，数据record固定1024B；ACK在安全921600下确认，排空/150ms后两端切baud，再等新baud BAUD_READY。按总wire字节目标节奏发送，最终binary FINAL给出预期/实际/错误/时长；host逐条验证模式字节、CRC、连续序号及重复/半包。30秒通过不等于长期所有USB拓扑都可靠；没有跳4M/6M，3M通过后无需测试更低档位。

初次READY因启动日志尾部粘连未被host识别，未开始高baud数据测试；保留失败目录/boot诊断，修正同步为寻找JSON起点后通过，不把boot ROM异波特乱码算成数据阶段错误。benchmark app-only烧录Hash verified，未写bootloader/分区，之后已换回8c。

| Synthetic callback workload | PROBE 100/s ×30s | PROBE 200/s ×30s | HANDSHAKE_ONLY ×30s |
|---|---:|---:|---:|
| 目标Data/CSI callback |15000|30000|15000|
| small candidate生成 |3000|6000|3000（仅计数）|
| 原子候选enqueued=output=host |3000|6000|0|
| 大帧预过滤 |12000|24000|0（HAND全部只计数）|
| HAND只计数Data |0|0|15000|
| synthetic EAPOL output=host |30|30|30|
| queue high water |2/24|3/24|1/24|
| queue drop / CRC / serial / parser / truncation |全部0|全部0|全部0|
| 最低free heap（B） |108116|108116|108116|

PROBE每个周期1个128B API payload小帧+4个1500B大帧；CSI114B，同一个wifi_csi_info_t经过正式CSI callback过滤/复制/队列/UART路径。EAPOL每秒1条经过同一promiscuous callback的synthetic输入；不是射频接收。Wi-Fi驱动NULL启动以保留部分内存成本，但未开启promiscuous或CSI RX；无线中断、真实包聚合和真实EAPOL缓冲语义不由本测试覆盖。

HANDSHAKE→PROBE→STOP短切换已实机synthetic验证：旧队列排空，MODE_ACK必须匹配mode，epoch递增，counters_reset=false（启动以来累计，不静默清零），queue_pending0、free_heap随ACK记录；STOP ACK和FINAL均收到、COM关闭。用户曾要求赶时间，100/s结束即停止并通知可拔线；后续用户重新连接并授权继续才完成剩余两档。

## 8c架构与过滤条件

独立工程sniffer_8c_staged，保留8b和独立uart_benchmark。24槽×约2KB池不扩大；UART921600安全启动，双向ACK切3M，CS8R保留62B外头/20B分段头/CRC，新kind7为CONTROL。

- HANDSHAKE_ONLY：目标Data/CSI只做最小头部检查和计数，不申请slot、不复制完整payload/CSI、不输出CSI_DATA；promisc只明确识别目标pair的clear EAPOL完整导出。
- PROBE_CAPTURE：目标source/TA、RA、Data、channel-estimate valid和rx_state0检查后，**API payload_len非零且<=256B**才成为候选；>256大帧在申请slot/大拷贝前计large_frame_filtered，不算queue_drop；缺失段或整条原子record超过现有slot容量计filter_other，不冒充完整候选。
- 决定导出的候选保留原始rx_ctrl、hdr、完整API payload、pointer delta、CSI、rx_seq等；不裁尾、不删CSI。对超slot EAPOL明确拒绝并计raw_truncated门禁异常，不输出冒充完整帧的片段。
- 控制协议MODE HANDSHAKE / MODE PROBE / MODE STOP，返回明确MODE_ACK及状态。UART输出用串行化锁保护数据/控制记录，保留全局record_serial顺序；模式切换排空旧数据，累计计数可作差。CRC由ROM实现，host zlib及实测逐条一致。
- counters包含target_csi_seen/candidate_seen/enqueued/output/large_frame_filtered/filter_other/handshake_data_count/queue_drop、EAPOL、CRC外传输统计及heap。过滤行为与资源丢弃严格分开。

### 为什么选择256，而不是一个精确长度

原probe为48B IPv4/UDP。独立未聚合QoS帧粗预算：26B MAC+8 CCMP IV+8 LLC/SNAP+20 IPv4+8 UDP+48应用+8 tag=126B union候选；当前API payload从hdr+24起，约102B。允许IPv4 options到60B、Addr4/HT control等MAC可选字段，候选API约可到152B；即便额外保留4B尾部候选也约156B。256留约100B保守余量，不依赖未经证明的精确tag/FCS语义，也不设精确下限去丢小背景帧。

历史v8b 3913条背景中3902条<=256、11条>256；F类失败窗口已落盘174条中106条<=256、68条>256（其中64条1554B）。这些只能说明过滤覆盖背景分布，不能估计未落盘183条的长度，也不能证明业务probe recall；v5/v6元数据记录没有可解密完整帧体，不能从其100包结果反推本过滤的实测召回。

**边界：** 小帧过滤不能在密文中识别CSID；会保留一些小背景。若probe被封装入>256B A-MSDU/大聚合MPDU，会被主动过滤；未来应记录聚合/重试/分片，不保证一个UDP一CSI或100%业务覆盖。不以本轮synthetic替代到场后的真实probe验证。

## UART配置与预算

PM_ENABLE未启用，UART_NUM_0/8N1/无流控/16KB TX ring。CH343驱动2.1.2025.7（2025-07-19），pyserial3.5的Win32 DCB允许设置3000000；API允许不是稳定证明，上述实测才是证据。C5默认UART_SCLK_DEFAULT定义PLL_F80M，benchmark显式选择该时钟。8c保留console配置，bootloader源码对C5走XTAL分支，属于源码推断、未读运行寄存器；8c getter实际3000000，不能把两工程getter差异抹平为同一时钟实测。

以下KB均十进制，8N1每字节10bit：

| 工况 | 数据wire预算（KB/s） | 与3M实测280 KB/s的关系 |
|---|---:|---|
| 921600理论line rate |92.160|不是稳定预算保证|
| 3000000理论line rate |300.000|未强顶理论值|
| 3M benchmark稳定窗口 |249.938 / 279.931|各30秒已测|
| synthetic128B payload，418B/record，100/s |41.8|约15%|
| 同上200/s |83.6|约30%|
| 保守最大candidate：556B，100/s |55.6|余224.4 KB/s（未扣控制）|
| 保守最大candidate：556B，200/s |111.2|余168.8 KB/s（未扣控制）|
| 未来probe 2～5/s，按556B上界 |1.112～2.780|20条合计至多11.12KB候选数据|

556B上界假设rx_ctrl64、最大36B MAC头、API payload256、当前HT CSI114，加20B分段头+66B外层/CRC；典型独立probe约392～456B，synthetic选418B。实际CSI长度可变，不能对所有PHY写死114；新固件保留原长/容量检查。

控制/STATS和EAPOL需额外预算，建议至少留2KB/s管理余量及更大突发空间。按250KB/s较保守工程上限，200/s最大候选+2KB/s约113.2KB/s、余136.8KB/s。921600下同工况已超过理论容量，不能靠池扩容解决；3M+过滤也不保证任意小帧洪峰零drop，未来仍须资源STOP门禁。

## 离线回归及重要修复

25项离线测试：6项wire/atomic/CRC/PCAP-tshark、10项握手结构/CSID/CRC/多观察关联、9项baud benchmark parser/mode ACK/合并ACK+FINAL/EAPOL索引/synthetic拒绝真实解密。确定性payload/CSI模式与完整EAPOL长度均对保存stream再次核验。

修复此前wpa2_gate8 converter仅接受RAW事件名、但wire decoder实际输出FRAME而可能忽略EAPOL的问题；新增4条synthetic EAPOL→PCAP回归，8c转换包含FRAME。此前并未进行真实握手，本修复不升级任何历史Gate A2结论。标准tshark从本轮synthetic EAPOL识别M1/M2/M3/M4为8/8/7/7、长度95，MIC为dummy，绝非有效真实4-way。

官方Wireshark4.6.9 WPA2-PSK CCMP/TKIP公共fixture回归：关闭解密ICMP0、启用5，证明离线工具链仍工作；使用已存公共fixture key配置，不读取或发布现场密钥。synthetic flag16被写入PCAP索引，真实解密入口拒绝synthetic工程记录，不能据dummy握手宣称现场解密通过。

## 下一次Jetson到场

串口和分阶段架构已具备工程验证基础，可按HANDSHAKE_ONLY→自己的Jetson正常重关联→核对完整一致4-way→MODE PROBE→20×48B UDP→Windows成熟工具解密→同record CSI关联的顺序推进。8c host Session已支持明确mode ACK/控制流，新wire工具支持kind7；旧capture8.py不是8c控制工具，不能直接混用。

**仍必须到场验证：** 网络/target pair/HT20与安全状态只读预检、回退确认、真实8c RF ACK/EAPOL长度与握手完整性、过滤对真实probe的覆盖、真实tag认证/解密及packet_id关联。当前不能宣布Gate A2或端到端最小PoC通过，也不直接进入JPEG/LiDAR。所有数据属于Synthetic throughput test，非无线捕获实验。

最终板sniffer-8c-staged-capture，source/build/bin/app/READY证据与hash见manifest，app-only0x10000 Hash verified、未重写bootloader/分区；最后MODE STOP ACK/FINAL已确认、RF capture false、COM10释放。RTS重启恢复安全921600，本轮不再硬件操作。
