# sniffer-7 raw-frame Gate A结果（2026-10-16）

**结果：未通过，已停止。** 成功app-only烧录/READY，真实Jetson QoS Protected帧可导出为PCAP并被tshark识别CCMP，但本地队列仍丢弃、严格FRAME↔CSI配对0、帧尾长度/完整MIC边界未充分证明。不能进入主动重关联/握手/UDP/现场解密阶段，也不能把多个阻塞捏成一个已确认根因。

## 操作边界与收尾

- 起初Jetson关机，SSH超时；用户开机后只读SSH确认2417MHz/channel2、HT1/VHT0、cur_bw/oper_bw/bwmode0、原MAC/IP/route/eth0和tx_bw_mode0x21，随后才烧录。HT20是驱动状态，不是逐PPDU测量。
- Windows COM10确认为CH343；烧录前RTS只读READY确认v6c，未CFG。原sniffer7离线候选导出pair双向Data超出本轮范围，先收紧成v7a：只目标Jetson→AP Data和可识别pair EAPOL，其他类型/设备只计数；CSI仅目标上行。
- v7a/v7b均只写0x10000 app，esptool Hash verified；不覆盖bootloader/partition。两个版本构建/容量通过，source/bin/ELF hash分别保留manifest，最终启动ELF匹配v7b build。
- 两轮只30秒被动背景采集；未发主动UDP、未改Jetson/AP/tx_bw_mode/eth0/ROS/服务/防火墙、未触发重关联或deauth、未输入密码给ESP、未现场解密、未操作传感器或机器人运动。
- 每轮STOP/FINAL成功；最终COM重开关闭确认释放，板现v7b已停止。收尾SSH只读仍同信道/带宽状态/地址/route/TX原值，新SSH全部退出。
- 各轮自然出现2条EAPOL标签，仅作为本轮被动数据保留，没有进行主动握手实验或据此尝试解密，不声称捕齐4-way。

## 数量闭合（实机直接证据）

| 项目 | v7a首轮 | v7b快照/缓冲复测 |
|---|---:|---:|
| 实测设备时间s |30.021419|30.025601|
| promiscuous总callback |29532|34043|
| 全部Data callback |19640|24023|
| 目标上行Data callback |437|1611|
| RAW enqueue/output/host |436/436/436|1462/1462/1462|
| RAW queue drop |1|149|
| CSI全部callback |7851|8343|
| 目标source/有效上行CSI callback |2600/2600|2676/2676|
| CSI enqueue/output/host |2600/2600/2600|2634/2634/2634|
| CSI queue drop |0|42|
| CSI empty/truncated、RAW truncated |0/0/0|0/0/0|
| UART write error |0|0|
| binary CRC/serial gap/resync/半record/metadata冲突 |全0|全0|
| Protected上行RAW |434|1460|
| tshark CCMP已确认/待解释 |431/3|1458/2|
| 严格shared/one-to-one/ambiguous keys |0/0/0|0/0/0|
| 队列高水位/深度 |24/24|32/32|
| final free_heap / 历史min_free_heap B |68048/1720|34700/12|

v7b：1611−149=1462；2676−42=2634，入队=固件输出=主机解析，serial连续/wire bytes也闭合。队列丢失发生在callback后，不是空口捕获率；不能用1462/2634推无线性能。不同窗口背景流量不同，不把第二轮更多drop解释为固定回归比例。帧/CSI均无截断，串口成功输出的记录未见传输损失。

## raw结构验证与边界

- 实际PCAP为radiotap/linktype127，未启解密；tshark可识别QoS Data、TA=目标Jetson、RA=AP、Protected及CCMP ExtIV/PN，标准字段与按可变头解析的PN逐条核对。FC、Duration、Addr1/2/3、seq/QoS、Retry/ToDS/FromDS等可恢复；Address4按实际FC判断，不能填造不存在的地址。
- 原始头/密文字节确已落盘，copied=SDK dump_len、CRC完整、无应用cap截断，且仅目标scope。**这只证明导出完整，不能自动证明SDK所给尾部就是完整802.11/CCMP tag边界。**
- 所有本轮RAW均dump_len=sig_len+4；它与现有SDK注释/原设计的长度解释不一致。尝试按尾部不同候选位置核对FCS，没有CRC吻合，不能把末4字节宣称FCS，也不能擅自减4/减8修包。
- 8字节CCMP header/ExtIV/PN可识别，header后的加密数据存在；导出末8字节只能叫CCMP128 tag候选，未解密/MIC认证，且当前真实MPDU尾边界未确定。因此“raw frame完全可供后续解密”尚未通过，不能伪造缺失字段或声称已证明截断。
- 少量Protected行未被tshark标CCMP但本地8字节头结构可读，尚未确定是解析器启发式/缺少协商上下文或其他原因，未当坏包删除。
- 初次审计把tshark布尔值只按1读取，实际输出True，使CCMP统计误报0；已修正并另存corrected分析，原结果保留。当前CCMP正确统计如表，Gate仍失败。

## FRAME↔CSI关联失败

保持原始键`timestamp+TA+FC+seq_ctrl`。首轮420条RAW与CSI共享前三项，但序号差16、32等，即一个或多个802.11序号。严格完整键shared0；既不放宽键、不补写seq、不宣称这些是同一MPDU。

v7b仅诊断性调整：回调入口立即快照rxmeta/24B头，再拷贝raw；保留原raw并让主机显式记录metadata conflict。复测无此冲突但严格配对仍0，说明该尝试没有恢复关联，不能宣称根因已定位。v6c历史窗口的有效匹配仍是历史事实，不因此删掉，也不能据此要求当前数据强行符合它。聚合/SDK回调语义/捕获条件差异均只是候选，尚未验证。

## 导出与内存尝试

- v7a采用24槽static pool；v7b为减少突发drop并减少初始化静态占用，改WiFi start后calloc、32槽，保持rawcap4096/csicap2048/TX ring16KB/921600、同样NULL信道与CSI配置。
- 11项离线回归/AST、build与分区通过，v7b app0xdbbd0/余14%；但实机仍出现drop，min_free_heap仅12B，不能再盲目扩大池。Gate A未通过；本轮不追加第三次硬件尝试。
- 后续可以先离线评估分离FRAME/CSI缓冲或变长内存池、回调实际raw长度/序号语义；在有新依据前不要重复当前失败配置，也不靠停Jetson服务或修改AMPDU/网络绕开问题。

## 当前阻塞与下一步

尚不具备进入“Jetson重关联→4-way→UDP→Windows解密”的条件。现有证据显示**三项待解决条件**：本地queue drop、严格raw FRAME↔CSI匹配缺失、raw尾部长度/完整CCMP tag边界未确认。它们是否有共同根因未知，不能为了满足“唯一阻塞”措辞而掩盖其他失败。

下一步先依据本地证据做离线诊断/方案评审，用户确认后才再安排修正版Gate A。Gate A通过后也必须单独获得主动重关联授权与现场独立管理回退；本轮没有进入下一阶段。

## 文件、版本与隐私

当前独立结果目录保存v7a/v7b raw binary、host时间侧录、normalized records、PCAP/index/joins、tshark字段输出、boot/SSH/flash日志、两版分析及manifest。原始Protected/EAPOL与实际标识仅本地；公开仅匿名汇总、字段说明和自有代码。

当前源码/build/app/READY为sniffer-7b-raw-snapshot；原v6c子项目源码/build未改但不再是板上运行版本。旧v7准备文档的“未烧录”只代表当时，已由本结果替代。

官方依据：[IDF5.5.5 C5 RX字段](https://github.com/espressif/esp-idf/blob/v5.5.5/components/esp_wifi/include/esp_wifi_he_types.h)、[Wireshark wlan字段](https://www.wireshark.org/docs/dfref/w/wlan.html)。实机字节/读数优先于注释理解；尚无证据确认SDK bug或特定聚合根因。
