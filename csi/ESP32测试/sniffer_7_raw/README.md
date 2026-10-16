# sniffer-7 raw binary候选（尚未烧录）

本子项目与现行sniffer_jetson/v6c分开；仅构建和离线验证，不代表设备运行版本。

固件：main/sniffer.c，ESP32-C5/IDF5.5.5；CS7R v1/62B LE头+payload+CRC32，pool24/raw4096/CSI2048/TX16KB/UART921600。CFG接受channel、目标STA和AP MAC，精确pair双向Data、目标uplink有效CSI；RAW dump_len按SDK不含FCS，超cap标truncated，不伪造/解密。

Windows工具：tools/raw7.py、capture_raw7.py（本轮未运行）、convert_raw7.py、extract_tshark_ids.py、associate_ids.py、test_raw7.py。旧v6c采集器不适用。

完整协议、吞吐预算、实际带宽/安全方式、离线测试及现场门禁见[HT主方案计划](../../HT主方案与WPA2业务关联计划_2026-10-16.md)。正式使用前必须用户确认；不可自动重关联/烧录/发UDP。

离线示例：python tools/test_raw7.py；python tools/convert_raw7.py <私有stream.bin> <新输出目录>。PCAP需要同名stream.bin.times.jsonl，不发明主机绝对时间；CRC/序号/长度错误时不生成PCAP。

raw帧/握手/PSK配置仅本地，公开仓库只放源码与匿名摘要。tshark解密由私有profile提供密钥，不提供密码CLI选项。关联保留多重候选，分片/A-MSDU完整祖先映射尚未实现，不声称1UDP=1帧=1CSI。raw吞吐/内存/握手及现场解密仍待硬件验证。
