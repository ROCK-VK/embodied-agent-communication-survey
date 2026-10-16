# WPA2 packet_id PoC：离线审计与执行前准备

2026-10-16。本轮目标为真实WPA2解密后恢复CSID packet_id并绑定同一CSI_DATA记录。**当前仅完成只读预检、离线审计和工具准备；尚未获现场回退确认，未重关联、未采握手、未发20包、未现场解密。Gate A2仍未通过。**

## 实机只读门禁

Jetson SSH成功：仍2.4GHz/2417MHz/ch2，原MAC/BSSID/SSID/IP/route/eth0及tx_bw_mode0x21；rf_info cur_bw/oper_bw0与既有枚举对照为驱动HT20，非逐PPDU测量。sudo仅执行wpa_cli status：COMPLETED/WPA2-PSK/pairwise CCMP/group TKIP。没有读取现场密钥。新增SSH已退出。

COM10 CH343在线，重启ESP读取READY为sniffer-8b；未CFG/ARM，板空闲、串口关闭。源码/bin/ELF与既有manifest SHA256相同，没有改固件/烧录。Windows现有tshark4.6.9可用，不安装驱动、不抓Windows网卡。

## 上轮3913条离线A2审计

- 逐条保存hdr复制长度、API payload_len、payload复制长度、pointer delta、sig_len、dump_len、union长度，私有record_layout_private.json可审计。
- 全3913：QoS头26B、payload指针差24、交叠2B一致、payload_len=sig_len/dump_len=sig_len+4；所有记录可形成ExtIV/PN候选并有至少8B tag候选空间。union长度118～1318B；这是容量/结构审计，不是认证或帧尾完整性证明。
- tshark关闭解密时3900条显示CCMP，13条显示TKIP。13条全为QoS Data（subtype8）、无fragment/more_fragments/A-MSDU标记、无malformed标记；12条127B、1条194B，未发现不足tag候选空间的短包。
- **13条的显示差异有具体依据：** Wireshark4.6.9在未确定算法时优先用`IV[1] == ((IV[0] | 0x20) & 0x7f)`判断TKIP，再检查CCMP保留字节。13条全部同时符合这个TKIP启发式与CCMP候选布局。当前真实单播协商CCMP，因此不能由显示标签断言它们实际使用TKIP。数据全部保留、不强制改算法、不伪造帧。
- 新合并转换工具对上轮原子记录输出与既有candidate PCAP逐字节完全一致。仍未证明现场CCMP tag完整，真实解密作为最终A2证据。

## 已准备的工具（尚未用于重关联实验）

- audit_a2_8.py：上述逐条长度/PN/tag候选及13条分类，关闭解密。
- wpa2_gate8.py：将同一串口流的CSI_DATA和可明确识别pair EAPOL按原顺序合并为标准radiotap PCAP及record索引；无跨callback Data join，不补FCS/裁尾。RAW EAPOL解析完整MAC/LLC、声明长度/Key Data长度、Key Info、replay、nonce、MIC等。
- 四向握手门禁保守限定本次WPA2-PSK/CCMP descriptor2/version2；依据pairwise/ACK/MIC/Secure/Install/方向/非零nonce和MIC分类M1～M4，再要求有序、M1/M2 replay一致、M3/M4一致且递增、M1/M3 ANonce一致。仅结构完整，不替代EAPOL MIC密码学校验。其它descriptor/版本记录为未分类而非自动通过。
- capture8.py新增本地stop-file、定期落盘、资源门禁自动STOP（drop/截断/缺失/写错/冲突或minheap<16KiB）。不控制任何网络接口，不扩大ESP池；尚未实机验证新增停止分支。
- decrypt_probe8.py：只通过本地既有Wireshark私有profile使用密钥，无密码CLI参数；关闭ignore protection，使用成熟tshark。要求完整握手及资源门禁，再提取目标Protected记录的UDP/CSID并验证CRC/模式/run_id/1..20。
- 最小严格关联还要求sender与receiver的run_id/packet_id/sender_mono_ns一致、该record有效CSI、无分片/A-MSDU祖先歧义。重试/多条观察保留，不强制一UDP一CSI；复杂重组保留但不计严格最小PoC。
- 6项wire/标准PCAP测试与10项握手/关联测试通过，含重复EAPOL不能凑4-way、nonce/replay错配拒绝、截断拒绝、CRC拒绝、多观察保留、缺receiver/分片不算严格关联。均为离线验证，非现场握手/解密通过。

## 下一步待用户确认的具体动作

待用户确认显示器键盘或独立管理回退已准备好后：ESP capture→核对ARMED/ch2/pair→仅让自己的Jetson正常重关联同一WLAN→验证完整且一致的M1～M4；不完整或资源门禁失败即STOP，不发UDP。完整后Windows receiver先启动，再发送20×48B/2～5pps、run_id固定的probe，继续采几秒并STOP，离线tshark解密并关联。

不改AP/密码/TX/驱动/服务，不deauth任何设备，不重启。SSID/PSK只用于私有profile，不进入日志/Git/报告。完成后检查SSH恢复、IP/route/eth0/TX，停止sender/receiver/ESP并退出SSH；不自动进入JPEG/LiDAR/VHT20/ESP AP。

## 目前最终指标状态

完整现场4-way、20包发送/接收、Protected成功解密、CSID恢复、packet_id↔CSI与Gate A2：**全部尚未执行**，不能归类为A～F失败。当前是用户要求的主动重关联确认门禁。若后续失败，区分A握手不足、B密钥初始化、C已证实tag校验失败、D已解密非probe、E CSID/CRC重组、F导出资源；无证据不能把一般“不出明文”强判C。

原始布局、PCAP、EAPOL/Protected/CSI、nonce/MIC、SSH/boot、解密输出/密钥仅本地。GitHub仅自有工具与匿名汇总。

## 官方依据

- [Wireshark4.6.9判别源码](https://github.com/wireshark/wireshark/blob/v4.6.9/epan/dissectors/packet-ieee80211.c)：IS_TKIP/IS_CCMP及算法未知时的优先分支。
- [Wireshark官方解密指南](https://wiki.wireshark.org/HowToDecrypt802.11)：WPA2-Personal私有密钥设置及握手要求；不把WPA3/Enterprise约束套用到当前WPA2-PSK。
