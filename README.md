# 机器狗CSI调研与实机验证

## 最新：HT20业务关联与raw7离线准备（2026-10-16）

当前驱动状态已核对为HT20；wpa_cli实际WPA2-PSK、单播CCMP/组播TKIP。旧FRAME只有元数据、没有密文或握手，不能直接生成可解密pcap。独立sniffer7 binary候选已构建、9项离线测试和tshark合成PCAP/官方WPA2样本验证通过，**未烧录、未重关联、未发新UDP**；设备仍最后验证的v6c。

当前优先HT20 raw Data+EAPOL→PC离线解密→packet_id关联，暂停VHT20/5GHz/TX参数。现场实验必须等用户再次确认和安全管理回退。[正式计划](csi/HT主方案与WPA2业务关联计划_2026-10-16.md)、[raw7源码与工具](csi/ESP32测试/sniffer_7_raw/README.md)。


当前重点是Jetson普通Wi-Fi上行的CSI采集与业务数据关联。较早的通信盘点与模拟仿真保留在[归档](归档/README.md)。

## 最新进度（2026-10-16）

| 项目 | 当前实证 |
|---|---|
| ESP32-C5 Router baseline | 已通过，不重复 |
| 旁路监听Jetson | legacy和HT Data+CSI均有来源/元数据实证 |
| HT导出优化 | v6c，30秒sanity和60秒主动窗口均零本地drop/解析错 |
| HT条件下100个低速UDP | 48B/5pps，100/100收到；窗口550FRAME/406HTCSI/406唯一匹配 |
| packet_id↔CSI | 未建立；Protected载荷不可见，CSI计数包含背景通信 |
| VHT20 | 尚未实测；当前Jetson仍2.4GHz/信道2 |
| Pi4B Nexmon / AX210 PicoScenes | 后续路线，未部署 |

当前固件为`sniffer-6c-compact-uart`，紧凑JSON+bulk UART、TX ring16KB/队列64、921600波特率，CSI原始字节不变。两个验收窗口回调→落盘计数闭合；旧高压未完整复现，不承诺所有负载零丢。

本轮Jetson网络、eth0、驱动、ROS、Mihomo和服务未改；没有切5GHz、写TX带宽、解密或接入传感器。所有新增会话已结束。物理验证仍保留RunA碰线失效、静态遮挡重复性不足的限制。

## 阅读入口

- [当前CSI阶段总览](csi/README.md)
- [最新HT导出优化与UDP报告](csi/ESP32测试/结果/c5_uart_optimization_20261016_124122/HT_UART优化与主动UDP结果.md)
- [下一阶段计划](csi/CSI下一阶段实验计划单_修订版_2026-10-15.md)
- [ESP方案](csi/ESP32_CSI测试方案.md)、[Pi4B方案](csi/树莓派4B_Nexmon_CSI测试方案.md)
- [当前固件](csi/ESP32测试/sniffer_jetson/main/sniffer.c)、[新版串口采集](csi/ESP32测试/sniffer_jetson/capture_compact_uart.py)
- [更新记录](csi/更新记录.md)、[历史归档](归档/README.md)

下一步等待用户确认后进行raw7 sanity，再在独立管理下授权Jetson重关联捕握手，之后PC离线解密和业务ID关联。VHT20暂缓；未经现场门禁不通过wlan0 SSH断网。

三条路线为ESP32-C5/esp-csi、Pi4B/Nexmon CSI、AX210+x86 Linux/PicoScenes。Atheros仅历史参考，FeitCSI退出主方案。公开文件均脱敏，原始记录/凭据/Flash/Agent规则仅本地；不宣称一UDP=一帧=一CSI。
