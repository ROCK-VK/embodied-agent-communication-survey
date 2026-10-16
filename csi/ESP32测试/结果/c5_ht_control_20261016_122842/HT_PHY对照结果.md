# ESP32-C5 2.4GHz HT/PHY对照结果

2026-10-16。本轮只在当前网络做HT/PHY对照，不是VHT20实验。**30秒被动sanity首次明确看到Jetson HT Data+有效HT CSI，但导出队列大量丢弃，按sanity门禁停止，未进入100包主动UDP。** 不把已完成的接收正结果扩大为完整低速UDP对照通过。

## 授权与设备状态

开始SSH再次确认Jetson wlan0：MAC<JETSON_MAC>、SSID <TEST_AP_SSID_2G>、BSSID<AP_2G_BSSID>，2417MHz/信道2，iwconfig为802.11bgn、72.2Mbit/s，IP<JETSON_WIFI_IP>，默认网关<AP_GATEWAY>经wlan0。rf_info当前宽度状态0，tx_bw_mode0x21。若不在此频段/信道应停止；本次满足条件。

COM10 CH343在线；复用板上sniffer-5-packet-id。采集器RTS复位ESP后READY版本正确，启动ELF前缀60eafdc14与此前v5构建记录一致；经UART发送CFG信道2/当前MAC，ARMED实际确认channel2、secondary0、NULL。没有烧录、构建或改固件；不是让ESP连接2.4GHz AP，不需SSID/密码。这里的运行时参数是启动CFG，不宣称支持在同一ARMED会话中热换信道。

源码仍启用promiscuous+CSI callback，acquire_csi_ht20/ht40启用、force_lltf0。原始CSI完整保存，没有复用legacy106字节/12bit26槽的物理解析器来解释新HT114字节；本轮只做PHY/来源/有效性/元数据关联。

本轮无Wi-Fi切换/tx_bw_mode写入/reload/unload/reboot/AP/防火墙/eth0/ROS/DDS/Mihomo/机器人/传感器/解密操作，不派发子Agent。

## Sanity数量与PHY证据

采集器报告30.250秒（含停止排空边界，不是精确均匀采样窗口）：

|项目|回调或设备计数|成功落盘|
|---|---:|---:|
|目标Data FRAME|8142|2571|
|有效目标Data CSI|1496|964|
|FRAME队列丢弃|5570|—|
|CSI队列丢弃|532|—|
|FRAME↔CSI共享元数据键|—|746|
|一对一匹配/两侧均HT|—|746/746|
|匹配歧义|—|0|

落盘964条CSI全部满足source与header TA为Jetson、QoS Data type2/subtype8、ToDS1/FromDS0、当前AP RA、channel2、estimate_valid1、rx_state0、first_word_invalid0、len=copied=114，raw buffer完整且非全零；rx_format（实际导出字段format=rx_ctrl.cur_bb_format）均为2，secondary原字段均0，RSSI -53至-43dBm。

落盘FRAME原始format2有2536条、format0有35条；后35条同时带有非零second原值48/112/176/240。C5 SDK中的RX second是unsigned8并注明HT40辅助信道，不能直接套信道配置enum或猜这些值含义。这35条原样保留、PHY解释待核验；不据此宣布实际11b帧或推翻964条有效HT CSI。746组正匹配两侧format都为2，不依赖这些未解释记录。

Protected按全部落盘记录重新计算：FRAME 2569/2571、CSI 964/964。现有capture summary的protected计数只覆盖主采集循环、未覆盖STOP后drain中的子字段，因此其protected_frame2554不是完整2571行的最终比值。本报告与analysis.json以全部records重新计数，不修改原summary或原始记录。Protected不可见业务ID属于预期边界，不算本轮HT失败。

## 官方字段依据（本轮重新联网核验）

- [ESP-IDF v5.5.5 C5 esp_wifi_he_types.h](https://github.com/espressif/esp-idf/blob/v5.5.5/components/esp_wifi/include/esp_wifi_he_types.h)：RX_BB_FORMAT_HT=2、VHT=3，format1为11a/11g别名；CSI HT20/HT40/VHT20采集开关分别定义，rx_state0是接收成功。
- [同版C5 CSI指南](https://docs.espressif.com/projects/esp-idf/en/v5.5.5/esp32c5/api-guides/wifi.html#wi-fi-channel-state-information)：cur_bb_format对应信号模式，len是字节长度；HT在无辅助信道的非STBC列为114字节，force_lltf0使用对应HT-LTF而非强制LLTF；estimate_valid1有效，first_word_invalid真时首4byte无效。

因此本轮**直接建立HT类上行Data与对应有效HT CSI实证**，不是“2.4GHz所以默认HT”。当前Jetson宽度状态0、CSI second0/114与HT20条件一致，但未另写HT-SIG带宽位解码，不把关联状态单独当成所有逐包带宽证明。he_siga1/he_siga2/rate等原值保留，未猜MCS或逐包带宽，不称VHT20成功。

## 导出瓶颈与为什么停止

- 有效DataCSI回调1496−设备队列drop532=964落盘，完整对账。
- 目标DataFRAME回调8142−队列drop5570=2572入队；落盘2571，相差1条FRAME。
- 2次host JSON解析错误实际是一条FRAME被STOP时wifi:ic_disable_sniffer驱动日志插入后拆成两个无效片段，原始保存；不是两条CSI解析丢失。
- 设备csi_empty/truncated/header冲突均0。新HT场景收到更多背景Data，现有921600 UART/JSON输出已饱和的判断是高可信推断；未做USB/UART物理吞吐基准，不称已证明唯一性能根因。
- FRAME与CSI共用有限输出队列，分别丢弃后只能在保留下来的数据中配对746组；不要求所有964条CSI一定有FRAME落盘，也不能用746/100或964/100算捕获率。

接收与SDK有效性这一层通过；导出质量门禁未通过。此前日志中sanity通过/可进入UDP只代表初步来源/有效性检查，**总体门禁结论由本条更正为未通过**。依用户“sanity不通过就停止”的要求，未启动Windows receiver、未执行Jetson sender、没有主动100包探针。不通过不等于C5不支持HT，恰好已取得HT正证据。

基于上述host时长，有效DataCSI回调约49.45条/s、落盘约31.87条/s，分开报告；回调丢弃部分的PHY metadata未保存，不能宣称1496条全为HT或完整空口采样率。

## 与昨日5GHz的对照（不同窗口/负载，非性能公平基准）

|项目|2026-10-15 5GHz/ch149|本轮2.4GHz/ch2被动sanity|
|---|---:|---:|
|采集时长|60.204秒|30.250秒|
|UDP sent|100|未执行，主动发送0包|
|UDP received|100|receiver未启动|
|目标Data FRAME落盘|63|2571|
|有效Data CSI落盘|63|964|
|FRAME↔CSI一对一|63|746（两侧均HT）|
|Protected FRAME|63/63|2569/2571|
|Protected CSI|63/63|964/964|
|CSI PHY/format|legacy OFDM/1|HT/2|
|CSI len|106|114|
|FRAME队列drop|0|5570|
|CSI队列drop|0|532|

观察数量受不同频段/PHY/背景流量/窗口/导出丢弃共同影响，不能把更多记录解释成固定提升倍数，更不能拿100个UDP作Wi-Fi帧真值。没有尝试业务ID恢复。

## 结束状态、文件与下一步

已收到ESP STOP/FINAL，COM10复开关闭证实空闲；未刷写，板仍v5。新增预检/收尾SSH均退出0，收尾仍原2.4GHz2417MHz/信道2、原IP/默认路由、tx_bw_mode0x21，eth0原配置。sender/receiver从未启动，无须终止未运行程序。

原始preflight/postflight、sanity UART/records/summary、analysis和manifest独立保存，不覆盖昨日；analysis_initial_diagnostic.json保留一次字段说明修正的中间分析，analysis.json为权威，计数一致。公开只放匿名报告/summary/manifest/analysis与本人离线分析脚本，不放raw日志或业务payload。

**下一步先在获准的独立任务中优化FRAME/CSI导出策略或紧凑记录，复做同条件sanity和100包UDP；之后再按管理回退门禁回5GHz、研究运行时TX限制、做VHT20。** 不停止现有Jetson业务来降低背景流量，不自动烧录/切网/改TX参数。本轮到此停止等待用户决定。
