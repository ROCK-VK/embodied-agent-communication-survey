# ESP32-C5 Open AP PoC 离线实现与构建报告

日期：2026-10-27
状态：离线实现、测试与构建完成；未烧录、未操作实机。

## 实现范围

- 新增独立 `OPEN_AP_POC`，没有移除/覆盖旧 `PROBE`、`HANDSHAKE_DIAG` 或 `HANDSHAKE_DUAL_DIAG`。
- ESP运行时启动 2.4 GHz/channel 2/HT20、无密码 SoftAP；SSID默认使用项目实验名 `CSI-C5-OPEN-POC`。配置只在运行时设置，不写入 NVS。
- ESP UDP receiver 监听 39001，复用现有 CSID v1 48-byte 协议，校验 payload pattern 与 CRC32，并统计收到、有效、CRC通过/失败、重复和唯一包数。
- SoftAP关联事件确定当前 station；CSI callback 对 ESP AP ↔ station 目标pair保留同条 CSI_DATA 中的 802.11 header、payload、CSI与metadata，并统计方向、Data/QoS、Protected/clear、CSID和导出健康计数。
- 新增 Jetson sender、ESP UART capture、CSI_DATA parser/analyzer。host仅在 sender记录、ESP `UDP_RX` CRC-valid事件和同一条CSI-valid CSI_DATA恢复出完全相同 `(run_id, packet_id)` 时判最小PoC通过；不以时间、帧序号或列表顺序推测。

## 离线验证

- Open AP 专项测试：9项通过。
- 完整 Python unittest：运行77项，76项通过、1项跳过。
- 新增 `send_open_ap_probe.py`、`capture_open_ap_poc.py`、`open_ap_poc.py`、`test_open_ap_poc.py` 的 `py_compile`：通过。
- ESP-IDF 5.5.5、Python 3.11.2、`PYTHONUTF8=1`，ASCII临时构建路径构建成功。
- App：963,984 bytes；SHA-256：`312238DB6B43134EF8AE2CAAE77723C07D114CC0C29AA5316CFDBCA26F3A34FA`。
- App分区为1 MiB，构建产物剩余84,592 bytes。分区表源码/布局没有修改；本轮没有写入bootloader、partition table、NVS或app。
- IDF仍报告既有UART VFS API弃用warning；不影响本次成功构建，后续可单独评估。

## 尚未验证与下一步

- 未烧录ESP；构建源码/产物与ESP当前运行版本是否一致未知。
- 未在ESP实机启动SoftAP、验证channel/BW读回、UDP socket接收或CSI_DATA明文解析。
- 未连接Jetson到SoftAP、未发送业务UDP；sender/receiver/CSI实机计数均为0/尚无数据。
- 下一次现场先确认COM10板上实际固件，再进行ESP-only启动与CSI sanity。Jetson网络切换必须提前通知用户并等待明确确认；用户手动操作，仅切USB Wi-Fi，保持eth0/ROS/Go2/MID360不动。
- 实机最多进行一轮20个48-byte probe，默认150 ms间隔；失败即停止，不自动重连或重试。至少一个完全一致的 `(run_id, packet_id)` 同时见于sender、ESP CRC-valid UDP接收与一条CSI-valid CSI_DATA，才能宣布最小PoC通过。

## 主要文件

- 固件：`ESP32测试/sniffer_8d_a_full_filter/main/capture_core.inc`、`main/staged.c`、`main/CMakeLists.txt`
- host：`tools/send_open_ap_probe.py`、`tools/capture_open_ap_poc.py`、`tools/open_ap_poc.py`、`tools/test_open_ap_poc.py`
- build临时副本：`D:/csiOpenApBuild`（不进入公开仓库）

本报告没有实机SSID/PSK、真实MAC/IP、sender日志、原始CSI、frame、PCAP或flash内容。
