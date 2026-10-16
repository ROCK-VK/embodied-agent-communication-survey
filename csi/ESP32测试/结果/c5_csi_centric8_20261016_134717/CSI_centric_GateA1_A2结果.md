# sniffer-8 CSI-centric：Gate A1 / A2 结果

日期：2026-10-16。当前板版本 `sniffer-8b-csi-centric`，ESP32-C5 rev1.0/4MB、ESP-IDF5.5.5、UART921600。只采两轮约30秒自然背景流量，未重关联、主动抓握手、发送UDP或解密；Jetson/AP/网络/服务均未修改。

## 结论

**Gate A1 在最终30秒窗口通过；Gate A2 尚未证明，不能进入握手/解密阶段。** 同一个CSI callback拷贝的header、API payload、rx_ctrl、CSI形成一条记录，避免v7跨回调严格join。该关联依据SDK回调语义，不是对射频芯片内部MPDU归属的独立验证，也没有证明某个业务packet_id。

| 指标 | 第一版v8 | 最终v8b |
|---|---:|---:|
| 有效目标Data CSI callback |4446|3913|
| 入队=输出=Windows原子记录 |4304|3913|
| CSI queue drop |142|0|
| Promisc EAPOL输出 / drop |0 / 0|0 / 0|
| 最低free heap（B） |7520|65060|
| 最终free heap（B） |101340|121260|
| 高水位 / 池槽数 |15 / 16|7 / 24|
| 传输CRC/序号/半包/写错/元数据冲突 |0|0|
| CSI空/截断、payload缺失/截断 |0|0|
| Protected记录 |4304|3913|
| 修正重叠后tshark识别CCMP |4275 / 4304|3900 / 3913|

第一版未通过，不删除历史；两次背景负载不同，不能据此宣称固定性能提升或所有负载零drop。最终window全部3913条为rx_format2（HT）、CSI114B、valid1、rx_state0、first_word_invalid0，源MAC/TA与目标Jetson一致、RA为AP，均为QoS Data/Protected。CSI总callback7776，包括非目标记录；不能把3913/7776当空口捕获率。

## 实现变化

- 独立`sniffer_8_csi`，v7源码/历史结果原样保留。Data仅由CSI callback导出；promiscuous只逐条导出可明确识别的目标pair明文EAPOL，其余只计数。最终无EAPOL记录，不代表没有漏握手。
- CSI_DATA包含同回调的rx_ctrl、hdr、payload、CSI及原/复制长度、rx_seq、时间戳、TA/RA/FC/seq_ctrl/PHY/RSSI/有效性字段；回调内立即复制，输出task负责binary/CRC/UART。
- CS8R外头62B、CRC32 4B；kind6为原子Data，分段头`<8Hi`20B，保存各段长度与payload相对hdr指针差，不暴露绝对内存地址。原始分段未改写。
- v8b单槽容量4096→2048，槽数16→24，总池约66KB→50KB；16KB UART TX ring保持。超cap显式标记/计数，当前窗口无截断，不保证未来所有大帧。
- v7严格join0不再是新方案阻塞，但聚合/序号语义根因仍未定；不能写成已修复SDK内部错配。

## ABI与API长度实测

编译及READY实测：target esp32c5、MAC version3、HE类型分支；rx_ctrl64B，promiscuous payload offset64；wifi_csi_info_t100B，hdr/payload/payload_len/rx_seq offsets为88/92/96/98。sig/dump是bitfield，不能使用offsetof；以编译器赋掩码得到首字节56/58，再逐条读回原始rx_ctrl，与C取值全部一致。

最终3913条均：协议QoS header长度26、payload指针=hdr+24，交叠2B逐字节相同；payload_len=sig_len，dump_len=sig_len+4。直接hdr+payload会重复QoS字段，首轮错误拼接仅偶然12条识别CCMP，已保留为失败诊断。正确候选MPDU为两段内存区间的union，长度24+payload_len；仅去除指针明确证明的重复范围，不猜±4/±8、不补尾巴/FCS、不替换原字节。

这些实测排除了当前host线格式对sig/dump的误解码，但不足排除SDK二进制语义问题；不能选定“注释错误/驱动Bug/聚合”为根因。

## A2为何仍未通过

候选PCAP显式关闭解密；3900条被tshark识别CCMP ExtIV/PN，13条保留为未解释，不删除凑成功率。CCMP识别说明字段结构可解析，不证明密文尾端authentication tag保留完整或有效。API两段区间可重组，也不自动证明它是完整原始MPDU；payload_len/dump_len命名和差值不能替代独立长度/尾界证据。

没有对现场tag进行密码学校验、没有捕完整4-way、没有现场解密或packet_id关联。`gate_a2_passed=false`表示证据未达到门禁，**不等于已证明tag缺失**。下一步先离线核验SDK保留/剥离边界或建立独立完整MPDU对照；若仍不足，再设计明确范围的后续实验，不能直接触发Jetson重关联。Plan B仅在确认CSI API帧体不完整后评估，当前不启用宽松跨回调join。

## 版本、验证与收尾

app-only0x10000两次Hash verified，未重写bootloader/分区；最终app0xdbf20，源码/bin/ELF SHA256见manifest，运行READY与ELF前缀核对一致。6项离线测试包含原子记录、CRC/序号、分段边界、元数据冲突、合成pcap/tshark、重叠字节拒绝；这些测试不能代替实机门禁。

STOP/FINAL已收到，采集进程退出、串口关闭。首尾只读SSH确认原2.4GHz/ch2、驱动HT20、MAC/IP/route/eth0及tx_bw_mode0x21，SSH退出。未切5GHz、改驱动/TX/ROS/服务、接传感器或机器人运动。

summary/manifest公开副本脱敏；stream、原始hdr/payload/CSI、records、PCAP/EAPOL、tshark、SSH/boot日志仅本地。

## 官方依据及证据等级

- [ESP-IDF v5.5.5实际头文件](https://github.com/espressif/esp-idf/blob/v5.5.5/components/esp_wifi/include/local/esp_wifi_types_native.h)明确CSI结构含hdr/payload/payload_len/rx_seq；应核对固定版本，而非master假设。C5实际走HE类型分支，不能套用普通非HE布局。
- [C5 v5.5.5 Wi-Fi指南](https://docs.espressif.com/projects/esp-idf/en/v5.5.5/esp32c5/api-guides/wifi.html)为CSI/promiscuous API依据。
- 同回调记录、ABI、指针重叠、计数/内存、HT有效CSI及网络未变：本轮实机软件直接确认。
- API原生关联：依据SDK语义及本轮header一致性；内部硬件归属没有独立抓包证明。
- 完整CCMP tag、WPA2解密、packet_id关联及长期/更高负载：尚未验证。
