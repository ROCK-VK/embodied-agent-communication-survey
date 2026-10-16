# WPA2最小PoC第1次执行：重关联前F类资源门禁停止

2026-10-16。用户已确认回退就绪、授权正常重关联。**实际重关联命令尚未发送：ESP ARMED后首先出现queue drop，自动STOP。本轮为F类本地导出问题，握手/20包/现场解密均未执行。**

## 预检及收尾

Jetson只读SSH再次确认原SSID/BSSID/MAC/IP/route/eth0，2417MHz/ch2、驱动HT20，tx_bw_mode仍0x21；sudo仅wpa_cli status，仍COMPLETED/WPA2-PSK/pairwise CCMP/group TKIP，未读PSK。source/bin/ELF哈希与baseline一致，ESP READY为8b、启动ELF前缀一致，未改固件/烧录。

capture确认ARMED后第一条STATS触发资源STOP，FINAL成功收到、进程正常退出并关闭COM10；新增SSH正常exit。未执行wpa_cli reassociate/nmcli等命令，不存在本次“重关联后恢复”证据；SSH在预检和退出时可用，现网维持原关联。

## 实测统计

| 指标 | 结果 |
|---|---:|
| 有效目标CSI callback |357|
| 入队=输出=host原子记录 |174|
| CSI queue drop |183|
| EAPOL输出 / raw drop |0 / 0|
| 队列高水位 |24/24|
| 最低heap / 最终heap（B） |31080 / 121260|
| UART写错、CRC、序号、resync、半包 |0|
| hdr冲突、payload缺失/截断、CSI空/截断 |0|
| Protected / tshark CCMP |174 / 174|

357−183=174，callback→queue→output→host闭合。174条均QoS Data、format2 HT、CSI114、valid1、rxstate0、firstinvalid0，交叠2B仍验证一致。错误是未入队记录丢弃，非已导出记录串口损坏，更不是无线捕获率。新增资源自动STOP分支首次实机验证成功。

ESP ARMED到FINAL monotonic跨度1.641550秒，host跨度1.797秒；包含排队/串口排空，不能当精确射频采样时长。原子记录合计164642 wire bytes，平均946.2B、最大1844B，64条API payload_len1554。921600/8N1理论上限92160B/s，当前输出已接近这一量级；host分块时间戳与缓冲不是独立UART物理测速，丢弃183条的长度未知。

直接证据为当前大帧/突发负载下队列满；未证明唯一根因或后台流量来源。上轮30秒零drop仅对应原窗口，不能推广所有负载。最低heap31KB并未逼近零；本次直接停止原因为queue drop，不扩大pool、不停现有服务、不盲重试。

## 任务要求的最终指标

1. 完整4-way：没有，M1/M2/M3/M4均0；重关联前已停止，不归A握手捕获失败。
2. 20包发送/接收：未执行，不能写成0/20丢包。
3. Protected成功解密：未执行；174仅结构识别CCMP。
4. CSID：未做probe/现场恢复。
5. 恢复packet_id：未执行。
6. packet_id与CSI原子关联：未执行。
7. CRC正确的最小端到端PoC：尚未建立。
8. Gate A2：尚未通过，缺真实现场解密证据，非已证实tag有问题。
9. 资源：drop183、队列24/24，门禁未过；heap31KB最低、传输/截断错误0。
10. 分类：F，无证据选择B密钥初始化或C tag认证失败。
11. JPEG sample_id/chunk_id→CSI：暂不能进入，先解决当前负载导出质量，再握手/20包最小PoC。

## 当前停止与下一步

没有改AP/密码/TX/网络/驱动/服务/ROS/eth0，没有重关联、UDP、传感器或狗运动。本轮不追加第二次硬件尝试。

下一步先离线依据帧长/突发和UART预算设计输出策略或受控采集安排，保留原子Data+CSI与pair EAPOL范围，明确任何采样/截断边界，不用扩池掩盖持续带宽不足。验证资源门禁后再考虑最小业务PoC；不自动进入JPEG/LiDAR/VHT20/ESP AP。

报告/匿名summary/manifest公开；原始stream、hdr/payload/CSI、PCAP/EAPOL、SSH/boot、凭据/解密输出均仅本地。此前准备审计保留历史，不代表本次已执行握手或解密。
