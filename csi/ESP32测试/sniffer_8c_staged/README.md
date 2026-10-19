# sniffer-8c staged capture

独立于sniffer_8_csi/8b；ESP32-C5、ESP-IDF5.5.5。main/staged.c含控制/synthetic输入，capture_core.inc为共享真实回调过滤/原子复制/队列/UART核心。默认安全921600，SET_BAUD旧速ACK→150ms→新速BAUD_READY；实测3M稳定。

CFG,SYNTH只设置合成pair并启动NULL driver，不启用promiscuous/CSI RX；SYNTH rate seconds手工调用正式callbacks，所有wire flag16，不能作为无线证据。真实CFG仅未来到场明确输入channel/target/AP后使用，本轮未执行。

MODE HANDSHAKE普通Data/CSI只计数；MODE PROBE只完整输出API payload<=256且容量足够的候选，大帧在slot申请/拷贝前过滤；MODE STOP关闭/排空并MODE_ACK+FINAL。kind7 CONTROL，计数启动以来累计，mode_epoch递增，不重置，ACK含队列/heap；只能在ACK匹配后认定切换。使用tools/staged_host.Session，旧capture8.py不兼容8c命令流。

tools/staged_host.py CLI只运行synthetic；wire8c保留原子分段与指针union；wpa2_gate8c处理FRAME EAPOL+CSI_DATA同流PCAP/索引；decrypt_probe8明确拒绝synthetic。没有自行实现CCMP。

已测100/s×30s候选3000/3000、大帧12000过滤；200/s为6000/6000/24000；HAND模式15000Data只计数、30EAPOL，drop/CRC/截断0、minheap108116B。短模式切换通过。真实RF/握手/tag/业务关联仍未验证；>256B聚合MPDU内probe可能主动过滤。

[完整报告](../结果/c5_8c_uart_synthetic_20261016_143027/8c_UART与Synthetic验证报告.md)。SDK配置/构建/固件/raw现场数据不发布；仅安全defaults、自有源码与匿名synthetic统计。

## 2026-10-19真实RF结果

capture_real8c.py新增实机UART控制，外部commands文件仅STOP/PROBE；PROBE强制完整一致握手和资源门禁，5项离线测试。真实首测只M1、CSI callback0，资源错误0，按A类STOP；Jetson正常重关联/SSH恢复已确认。未PROBE/UDP/现场解密。先诊断8c与8b RX初始化/filter差异，不称synthetic已覆盖真实RF。[结果](../结果/c5_8c_real_wpa2_20261019_171844/8c真实握手结果.md)。
