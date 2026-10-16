# ESP32-C5 HT UART导出优化与100包UDP结果（2026-10-16）

## 结论与验证范围

**实机直接确认：** 当前2.4GHz/信道2条件下，v6c的30秒被动HT sanity和60秒主动UDP采集窗口均通过本地导出质量门禁。100个48B业务UDP以5pps发送，Windows收到100/100；主动窗口550条目标Data FRAME、406条有效HT CSI、406组一对一元数据匹配。所有本地队列drop、UART解析/写错误、CSI空/截断均0。

**尚未证明：** 406组包含背景通信，不能逐一归属于100个UDP；packet_id↔CSI仍为0，不能声称一UDP=一帧=一CSI，也不把406/550或406/100当无线捕获率。HT类接收+有效HT CSI已经成立，“只支持legacy OFDM监听”已失效；VHT20仍未实测。

## 本轮边界

- Jetson保持原2.4GHz/2417MHz/channel2；仅SSH读状态及临时标准库UDP发送器，临时文件自动清理。eth0/路由/驱动/TX参数/ROS/Mihomo/服务均未修改，未改防火墙、AP、网络连接或安装依赖。
- ESP以NULL promiscuous模式匹配本次SSH重新确认的目标TA/MAC，不关联AP；CSI通过CH343 COM10→UART→Windows导出，无Wi-Fi CSI回传。
- 未执行5GHz切网、tx_bw_mode写入、WPA解密、raw frame/EAPOL导出、ESP AP、相机/LiDAR/狗运动。

## 固件与主机改动

- 当前固件`sniffer-6c-compact-uart`，IDF5.5.5/target esp32c5；保留CSI配置及原始SDK字节，未做IQ重解释。
- FRAME输出紧凑字段timestamp、TA、RA、FC、seq_ctrl、PHY/rate/channel/second/RSSI/rx_state；Protected/type/ToDS等由FC原位解码；CSI增加来源、valid/first_invalid、长度、rx_seq/SIG和raw hex。
- 使用`uart_write_bytes`整条写出，绕过IDF VFS逐字节TX调用；UART仍921600，增加16KB TX ring，事件队列32→64。Management/Control只计数、不逐条导出。
- 新增入队/输出/串口字节/写错误/队列高水位/记录序号；主机保留私有原始紧凑行并还原旧分析schema，统计含STOP drain，核对序号连续及callback→queue→UART→落盘闭合。
- 仅关闭ESP的wifi/main_task普通日志，修复STOP日志污染；Jetson服务不变。仍是紧凑JSON+hex，**未改binary**，当前两窗口已达零drop，后续高压若再饱和才评估binary framing。

## 真实执行与失败保留

| 轮次 | 时间s | FRAME callback/落盘/drop | valid CSI callback/落盘/drop | 两侧HT唯一匹配 | 解析错 | 判断 |
|---|---:|---|---|---:|---:|---|
| 历史v5 HT sanity |30.250|8142/2571/5570|1496/964/532|746|2片段|导出失败；1FRAME被日志拆坏|
| v6紧凑+bulk、无TX ring |30.078|2846/1117/1729|740/575/165|434|1|门禁失败，不发UDP|
| v6b +16KB TX ring/队列32 |30.187|966/957/9|445/444/1|443|1|门禁失败，不发UDP|
| v6c +队列64/日志修复 sanity |30.062|224/224/0|165/165/0|165|0|通过|
| v6c 主动UDP窗口 |60.015|550/550/0|406/406/0|406|0|通过，100/100 UDP|

不同窗口背景负载显著变化，不能宣称旧高压负载已完整复现或量化固定性能提升。v6/v6b失败证据及各自源码留在本地，不删历史。v6b的非JSON行是main_task返回日志，数据事件序号仍完整；v6c已修复。

## 最终验收与计数闭合

- sanity事件389条，FRAME224/CSI165；主动事件956条，FRAME550/CSI406，序号均从1连续、重复0。
- 两轮callback减queue drop=入队=固件输出=主机落盘，各项闭合；STOP/FINAL正常。队列高水位分别27/64与17/64。
- 主动窗口406条CSI均format2（官方HT）、len/copied114、valid1、rx_state0、first_word_invalid0、channel2/second0，来源+TA是当前Jetson，ToDS1/FromDS0；406组FRAME两侧均HT，无歧义。
- 主动FRAME 489条format2、61条raw format0且second原值非零，保留未知编码，不推成11b或带宽异常；未用legacy12bit映射解释HT114。
- Protected：主动FRAME548/550、CSI406/406；业务ID可见数0符合旁路加密限制，不是本阶段质量门禁失败。
- 执行顺序：Windows receiver先监听，ESP READY/ARMED后才启动Jetson sender。100个有效RX时间全部在采集窗口内；receiver缺失/重复/无效均0。sender仅100×48B、间隔0.2s。
- ARM时free heap30164B（输出任务创建前），队列分配/两窗口运行通过；未验证长时间或更高突发负载内存余量，不盲目再扩队列。
- IDF构建app0xdbb80，app分区余14%；esptool app-only烧录0x10000并校验hash。manifest记录源码/bin/ELF/主机脚本SHA256，READY/启动日志提供设备版本证据。原bootloader/分区未重写。

## 版本与证据

`manifest.json`、`summary.json`、`sanity_v6c_analysis.json`、`udp_analysis.json`、`packet_analysis.json`为摘要；各采集子目录的raw UART/records、endpoint日志、SSH输出及失败候选仅本地保存。新版工具为`compact_uart.py`、`capture_compact_uart.py`、`audit_compact_export.py`，4项离线测试通过及实机构建/烧录/上述两窗口通过。

构建失败经验：旧生成响应文件包含自身`@cflags`引用，导致too many @-files；仅清除生成文件递归引用、保留实际march/链接标志后成功，未改SDK源码。

## 下一阶段顺序（本轮不执行）

1. 先核对匹配RTL8821CU源码的tx_bw_mode 0x21/nibble/运行时作用和恢复方式；没有足够证据不写值。
2. 具备现场显示器/键盘或验证过独立管理通道后，才允许安排Jetson回5GHz并只读核验149/PHY/原宽度。当前wlan0 SSH不得直接承担无回退切网。
3. 临时VHT20候选验证：48B/5pps/100包可比档，另约1200B/10–20pps/20–30秒PHY激发档；须另行授权实际网络/驱动写入。必须看到Data的format=VHT及有效VHT CSI，链路显示VHT不能代替。
4. PHY/导出明确后再设计raw frame+EAPOL、Windows离线WPA2解密与packet_id↔FRAME↔CSI；不在C5上做完整解密。ESP AP保留对照/Plan B，也须验证映射，不能假定一UDP一CSI。
5. 最后才JPEG、LiDAR、t+(x,y)+sample_id。当前只完成前两阶段，不声称全路线完成。

## 官方依据与证据等级

- [ESP-IDF5.5.5 C5 Wi-Fi/CSI](https://docs.espressif.com/projects/esp-idf/en/v5.5.5/esp32c5/api-guides/wifi.html#wi-fi-channel-state-information)：CSI回调任务中应快速处理/转队列，输出移至独立任务。
- [IDF5.5.5 UART VFS源码](https://github.com/espressif/esp-idf/blob/v5.5.5/components/esp_driver_uart/src/uart_vfs.c)：uart_write循环逐字节调用tx_func；直接bulk UART绕过此层是源码依据，实际效果以上述实机计数为准。
- [官方PHY字段头文件](https://github.com/espressif/esp-idf/blob/v5.5.5/components/esp_wifi/include/esp_wifi_he_types.h)：format2=HT。本轮值来自实机，未仅凭配置认定PHY。
- 高可信推断：突发导出阻塞是剩余queue drop的重要候选，TX ring/队列调整后本窗口为零；背景流量不同，不能归因于单一参数或证明全负载能力。
- 尚未验证：更高压/长期零丢、HT IQ完整映射、VHT20、业务ID关联、解密及传感器链路。
