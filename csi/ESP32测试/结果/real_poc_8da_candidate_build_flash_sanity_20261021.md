# 8d-a EAPOL/filter 候选构建、烧录与被动 sanity

## 结论

候选固件已在本机成功构建并写入 ESP32-C5（COM10），esptool 对 bootloader、app 和 partition table 均报告哈希校验成功。设备重启后返回预期的通用固件标签并接受 channel 配置及 MODE 命令。

随后进行的 12 秒被动采集**未通过目标 CSI sanity**：设备在 channel 2 收到空口回调，但有效目标 CSI 为 0。采集结束后只尝试了一次 5 秒只读 SSH 查询 `iw dev wlan0 link`，返回 exit 255、未取得无线状态；未重试。用户确认目前不在实验室且 Jetson 不在现场，因此本轮不能继续核验网络状态，也不进入用户手动断开/连回实验。

## ESP-IDF 环境问题与修复方式

- 确认使用 ESP-IDF 5.5.5 和 `D:\Espressif\python_env\idf5.5_py3.11_env\Scripts\python.exe`（Python 3.11.2）。
- `D:\Espressif\esp_idf.json` 已选择正确的 3.11 环境。此前导出失败并非该配置指向了 3.13，而是启动 `export.ps1` 时 PATH 优先命中 Anaconda Python 3.13；IDF 的 `activate.py` 根据调用它的解释器版本推导 `idf5.5_py3.13_env`，该目录不存在。
- 在构建进程中显式设置 `IDF_PYTHON_ENV_PATH`，并将 IDF venv 的 `Scripts` 前置到 PATH，IDF Python 检查通过。
- 中文工作目录下，Kconfig 曾受 Windows cp936 默认解码影响；设置 `PYTHONUTF8=1` 后通过。随后 GCC 对非 ASCII 源路径报文件系统编码错误，因此将源代码和配置复制到 ASCII 临时目录构建。构建前核对的 36 个源/配置文件 SHA256 与工作区一致；没有修改工作区源码来规避构建问题。

## 构建与烧录

- 目标：ESP32-C5，IDF 5.5.5，Python 3.11.2。
- 构建结果：`sniffer_8d_a_full_filter.bin`，905,200 字节；app SHA256：`FBEF9E4380B1FF453EB1852BAB4D1B053F2C05445FA62426AB4FBECCE7F748D1`。
- 烧录端口：COM10 / CH343；芯片识别为 ESP32-C5 revision v1.0，Flash 4 MB。
- bootloader、app、partition table 的写入均返回 `Hash of data verified`，随后通过 RTS 硬复位。
- 随后的串口采集握手返回版本标签 `sniffer-8d-a-full-filter`，并成功处理 CFG、channel readback、MODE PROBE 和 MODE STOP。设备协议没有提供 app SHA 的独立读回，因此不能仅凭版本标签证明芯片运行镜像与上述 SHA 完全一致。

## 12 秒被动采集

- ESP 配置 channel：2；实际读回 channel：2；`channel_readback_ok=true`。
- `MODE_ACK` 确认 RF capture enabled；窗口到时后收到 STOP ACK 与 FINAL，RF capture disabled。
- Promiscuous callback：474（Management 459、Control 0、Data 15、Misc 0）。
- CSI callback：4；来源目标 0、来源其他 4、有效 channel estimate 0、目标有效 CSI 0、CSI_DATA 导出 0；4 条均归为 legacy PHY，HT CSI 为 0。
- 资源/串口：queue drop 0、write errors 0、截断 0、空 CSI 0，最低 free heap 113,412 B。
- 这些计数表明控制面和回调入口有响应，但没有证明 Jetson 的 CSI 接收路径正常。唯一一次采集后只读查询未取得 Jetson 当前无线信道；目标 CSI 为 0 的原因仍未知，不能区分 Jetson 当时不在 channel 2、目标无线活动不足或固件筛选路径。

## 后续门禁

1. 不进行 Jetson 断开/连回，不做远程 reassociate，不自动重试。
2. 等 Jetson 回到现场后，只读确认当前连接和信道；确认处于 channel 2 后，再对同一固件做一次短时被动 sanity。
3. 只有目标有效 CSI 大于 0，且队列/串口错误与截断为 0，才汇报并等待用户手动执行一次 Wi-Fi 断开/连回。

私有原始流保留在本地 `ESP32测试/结果/real_poc_8da_candidate_passive_sanity_20261021_200849/`；不发布串口原始数据、现场 MAC/IP、凭据或构建二进制。
