# sniffer-8 CSI-centric

ESP32-C5 / IDF5.5.5；独立于历史sniffer_7_raw。当前固件sniffer-8b-csi-centric，UART921600、NULL监听、不关联AP。CFG须显式指定当次信道与目标/接收端MAC，不存Wi-Fi密码。运行capture会通过RTS重启ESP；必须在明确授权实验时使用，不改变Jetson网络。

Data由单个CSI callback立即复制rx_ctrl、hdr、payload、CSI入队。Promiscuous只导出可明确识别目标pair的EAPOL，其它仅计数。pool24×约2KB，超cap显式标记；STOP关闭接收并排空，FINAL输出计数及heap。

CS8R v1外头62B+body+CRC32 IEEE4B，kind6 CSI_DATA；body前20B为`<8Hi`：hdr复制长度、API payload原长/复制长、CSI原长/复制长、rx_ctrl长、sig_len、dump_len、payload-hdr有符号指针差；随后rx_ctrl/hdr/payload/CSI。其它控制kind沿用3/4/5，EAPOL RAW为1。字节序LE，不直接把C结构作为跨平台wire头。

当前实测QoS hdr26而payload=hdr+24，两段重叠2B；host按指针范围及重复字节一致性作union，不盲拼接、不猜帧尾。原始两段完整保留。若有gap/冲突，分析失败而非填补。

工具：wire8.py协议与原子段解码；capture8.py串口采集/STOP；analyze8.py候选PCAP与Gate A1审计（显式关闭解密）；test8.py离线6项回归，CSI_TEST_TSHARK环境变量指定已有tshark路径。

最终背景30秒3913/3913、drop0、minheap65060B，A1通过；A2 tag完整性未证明，不进入握手/解密。详情见[结果](../结果/c5_csi_centric8_20261016_134717/CSI_centric_GateA1_A2结果.md)。build/sdkconfig/bin/raw/PCAP/现场标识仅本地。纯构建通过不等于烧录；本次源码/build/app/READY已按manifest核对。

## WPA2 PoC准备

audit_a2_8.py审计API分段及候选尾界；wpa2_gate8.py合并CSI_DATA与明确EAPOL为PCAP/索引并核对同一4-way；decrypt_probe8.py使用既有私有profile调用tshark并验证CSID/CRC及sender/receiver一致性。capture8支持stop-file与资源失败STOP。6+10项离线回归通过；新停止分支与真实握手/解密尚未实机验证，ESP固件仍8b。必须在用户确认现场回退后才重关联，握手不足不发UDP。
