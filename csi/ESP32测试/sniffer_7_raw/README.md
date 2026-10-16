# sniffer-7 raw binary（当前v7b，Gate A未通过）

当前main/build/app/READY为sniffer-7b-raw-snapshot，app-only烧录，设备已STOP；现行v6c仅作为历史对照。Gate A未过，不进入重关联/主动EAPOL/UDP/现场解密。

CS7R v1：62B LE头+payload+CRC32；raw cap4096/CSI cap2048、WiFi启动后calloc pool32、TX16KB/UART921600；精确目标上行Data+可识别pair EAPOL，普通AP下行不导出；其它流量只计数。

最新30秒RAW1611 callback/1462落盘/drop149，CSI2676/2634/drop42；binary完整、严格FRAME↔CSI匹配0，dump/sig帧尾长度未确认。头部/CCMP标准解析存在正证据，不代表完整MIC或后续解密已验证。入口snapshot和扩大pool没有恢复匹配，历史min heap12B，不盲目重复失败方案。

工具：tools/raw7.py、capture_raw7.py、convert_raw7.py、audit_gate_a.py（明确禁解密）、extract_tshark_ids.py、associate_ids.py、test_raw7.py。11项离线回归通过，不能替代Gate A；检测raw/header冲突保留证据且Gate失败。现场Protected帧/握手/PSK不公开。

详细进展和现场门禁见[HT主方案](../../HT主方案与WPA2业务关联计划_2026-10-16.md)。下一步只离线诊断，用户确认后才安排修正版Gate A。
