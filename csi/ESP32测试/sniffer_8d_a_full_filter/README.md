# sniffer-8d-a full promiscuous filter diagnostic

基于 sniffer-8c-staged 建立的单变量 A/B 诊断独立固件版本（ESP32-C5 / ESP-IDF 5.5.5）。

## 核心改动

1. **唯一真正影响 RF 的单变量**：
   将 8c 中的 `WIFI_PROMIS_FILTER_MASK_DATA` 改回历史 8b 使用的 full mask：
   `WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_CTRL | WIFI_PROMIS_FILTER_MASK_DATA | WIFI_PROMIS_FILTER_MASK_MISC`。
   其余 RF 时序、信道设置、动态使能/禁用逻辑、staged 架构、CSI 配置、3M UART 均与 8c 严格一致。

2. **纯观测增强（不改变 RF 行为）**：
   - 增加 Promiscuous 回调入口类别统计：`prom_cb_total`, `prom_mgmt`, `prom_ctrl`, `prom_data`, `prom_misc`。
   - 增加 CSI 回调首行入口总计数：`csi_cb_total`。
   - 增强 CSI PHY 分类与合法性统计：`csi_source_target`, `csi_source_other`, `csi_valid_channel_estimate`, `csi_rxstate_ok`, `csi_target_valid`，以及 `rx_11b`, `rx_legacy`, `rx_ht`, `rx_vht`, `rx_other`。
   - 增加 `esp_wifi_get_channel()` 与 `esp_wifi_get_mode()` 读回检查与 CONTROL 状态导出。

## 实验与验证

- **离线回归**：通过 20 项协议与 parser 回归测试，CONTROL 状态导出新增字段解析测试全部通过。
- **实机双轮被动 RF 验证（Jetson 保持原连接不触发断网）**：
  - Run 1（30.0s）：`prom_cb_total = 3,130`，`csi_cb_total = 1,544`（从 8c 的 0 彻底恢复），目标有效 CSI 128，HT CSI 128，未发生队列丢包或内存异常。
  - Run 2（15.0s）：`prom_cb_total = 1,487`，`csi_cb_total = 851`，目标有效 CSI 76，HT CSI 76。
- **结论**：在其余 8c RF 行为保持不变时，将 promiscuous filter 由 DATA-only 恢复为 full mask，是恢复 CSI callback 的关键直接支持变量。

## 2026-10-21 HANDSHAKE pair-clear 后续

- HANDSHAKE 额外 pair-small 诊断只接受配对方向、Protected 位清零且长度不超过256B的候选；原 EAPOL 识别/入队逻辑独立保留。这是筛选候选，不把 Protected=0 当作 EAPOL 证明。
- 8d-a离线回归20项通过，wire测试6项通过（1项可选 tshark 集成未运行），旧 WPA2 结构测试10项通过。parser新增 M4 Secure 位检查，并将未解析成EAPOL的 Data FRAME 保留在 PCAP。
- ESP32-C5 / ESP-IDF 5.5.5 build与COM10烧录校验完成。约10秒被动sanity三窗中，第三窗有10条目标来源CSI、10条有效；全局HT计数88；queue/CSI/RAW drop、串口错误与截断为0，最低heap105828B。前两窗目标CSI为0；短窗口波动不能单独判作固件故障。
- 没有捕获完整 M1–M4、没有UDP或WPA2现场解密。完整匿名汇总见[后续报告](../结果/8d_a_pairclear_followup_20261021.md)。

### 16:00 被动 CSI 回调复测

- HANDSHAKE_ONLY 被动监听28.377秒，采集前 Jetson 只读状态为2.4 GHz / channel 2；无重关联、无UDP。
- csi_cb_total=1713，目标来源/有效 CSI 为16/16，全局 rx_ht=597；queue/raw/CSI drop、写错、截断和空CSI均0，最低heap86332B，MODE STOP和FINAL正常。
- 没有导出 CSI_DATA 原子记录，没有EAPOL/M1–M4；仅通过CSI callback层sanity，不表示业务记录或握手成功。

### 16:12 单次远程重关联尝试未确认

- HANDSHAKE_ONLY 在channel 2运行约239秒，CSI callback 11927、目标来源有效CSI 1309、HT分类3286；EAPOL与M1–M4均0，CSI_DATA原子记录0。
- Queue/raw/CSI drop、写错、截断和空CSI均0，最低heap58104B；采集正常因duration_limit结束并收到STOP/FINAL。
- 仅发出一次用户授权的远程 reassociate，命令返回exit code 1。其后约18秒SSH端口观察44/44可达，没有确认断网；实际是否发生短暂无线状态变化未知。
- 下一轮改为用户手动控制一个断开/恢复周期：先重新ARM并检查CSI、SSH与Wi-Fi状态，再等用户操作；不远程重试、不自动重连。完整M1–M4通过离线解析确认前，不进入PROBE、UDP或解密。
- 详细匿名结果见[单次重关联尝试报告](../结果/real_poc_8da_single_reassociate_20261021.md)。

### 20:08 候选构建/烧录与被动 CSI sanity

- 修复构建调用环境：明确使用 ESP-IDF 5.5.5 和 Python 3.11.2 venv。此前 `export.ps1` 被 PATH 中的 Anaconda Python 3.13 启动，IDF 因而推导出不存在的 `idf5.5_py3.13_env`。显式指定 `IDF_PYTHON_ENV_PATH` 并前置 IDF venv 后构建成功。
- Windows 中文目录下另有 Python 默认 cp936 解码和 GCC 非 ASCII 路径问题；通过 `PYTHONUTF8=1` 与源/配置 SHA 一致的 ASCII 临时构建副本解决，没有改动 Jetson。
- 候选 app 大小 905,200 B，SHA256 `FBEF9E4380B1FF453EB1852BAB4D1B053F2C05445FA62426AB4FBECCE7F748D1`。COM10 烧录时 bootloader、app 和 partition table 均报告哈希验证成功；设备返回通用版本标签 `sniffer-8d-a-full-filter`。芯片没有独立 app SHA 回读接口。
- 12秒被动窗口读回 channel 2 并正常 STOP/FINAL；promiscuous callback 474、CSI callback 4，但4条都不是目标来源，有效目标CSI与CSI_DATA均为0。queue drop、串口写错、截断均0，最低heap 113412B。
- 因未核实 Jetson 本次窗口中的无线信道，目标CSI为0的原因尚不确定；固件启动和串口控制正常，但目标CSI sanity **未通过**。不进行断开/连回实验。后续先只读核对 Jetson channel，再复测被动CSI；通过后才等待用户手动做一次断开/连回。
- 采集结束后唯一一次5秒只读SSH查询未取回状态（exit 255），没有重试，也没有向Jetson发送配置或网络操作命令。
- 用户确认当前不在实验室、Jetson不在现场；后续需等设备回到现场再只读核对信道。当前不安排断开/连回实验。

### 2026-10-26 候选固件被动 CSI sanity

- 用户报告 Jetson 已连 2.4 GHz。只读 SSH 查询未能返回系统链路状态（exit 255）；没有重试或修改 Jetson。
- ESP 在 channel 2 监听 12 秒并正确读回 channel；CSI callback 710 次，其中来源匹配目标的有效 CSI 为44条。CSI队列/串口错误/截断为0，最低heap 109484 B；MODE STOP/FINAL正常。
- CSI_DATA记录为0，44个大帧候选超过当前256 B上限并被过滤。该轮通过目标CSI callback sanity，但没有验证EAPOL、完整握手或业务packet_id记录。
- 结果可支持准备一次用户手动断开/连回实验；Codex不远程重关联。须先ARM限时监听并确认状态，再通知用户操作。
- 详细匿名统计见[2026-10-26被动CSI sanity报告](../结果/real_poc_8da_candidate_passive_sanity_20261026.md)。

### 2026-10-26 单次手动断开/连回

- 用户在 Jetson 本机手动完成一次 Wi-Fi 断开并连回；Codex未远程重关联、未修改网络，也未自动重试。
- HANDSHAKE_ONLY运行约170.7秒；CSI callback 8952、目标有效CSI 555。queue/raw/CSI drop、串口错误与截断均0，最低heap 50740 B，正常STOP/FINAL。
- 只捕获并解析到一条 EAPOL-Key M3；M1、M2、M4均0，完整四次握手不成立。CSI_DATA原子记录0，未做WPA2解密或packet_id关联。
- 单次结果未达到握手门槛；不再自动/重复重连。详细匿名报告见[单次手动重连结果](../结果/real_poc_8da_manual_reconnect_20261026.md)。
- 详细匿名统计见[候选构建、烧录与被动 sanity 报告](../结果/real_poc_8da_candidate_build_flash_sanity_20261021.md)。

### 2026-10-26 M3 周边离线核验

- 该轮raw只含一条M3；host parser、单帧PCAP和tshark均识别同一消息。M1/M2/M4在raw日志中无可识别记录，空口缺失与固件候选过滤尚无法区分。
- 已加入只改变HANDSHAKE_ONLY统计、不改变候选筛选和逐包导出的拒绝原因计数。27项离线回归通过，IDF 5.5.5隔离本机构建通过；尚未烧录。详见[匿名离线分层审计](../结果/real_poc_8da_manual_reconnect_20261026.md)。

## 2026-10-26 HANDSHAKE_ONLY 筛选漏斗计数

后续诊断固件只增加聚合计数，不改变候选 gate、入队条件或 CSI 处理：

- `prom_data`：全部 promiscuous Data callback；`prom_target_related_data`：通过有效 Data header 并且 TA 或 RA 命中目标 STA 的帧；`pair_seen`：精确 Jetson↔AP 方向帧。
- `hs_up_seen` / `hs_down_seen`：HANDSHAKE_ONLY 中按当前地址判断得到的精确上/下行 pair；Protected/clear-small及新增 `hs_pair_protected`、`hs_pair_unprotected`、`hs_pair_len_le256`、`hs_pair_len_gt256` 统计该 pair 的加密状态和长度分布。
- `hs_pair_small_accepted`：满足既有精确 pair、未加密、`<=256B` 条件的候选数，不代表 EAPOL。
- `hs_llc_snap_candidate` 与 `hs_ethertype_888e_candidate`：目标相关、可按 LLC/SNAP 检查的 clear Data 中，分别匹配 SNAP 前缀和 EtherType `0x888e` 的数量；它们是候选特征统计，不替代 host EAPOL-Key 解析。
- `hs_filter_protected`、`hs_filter_oversize`、`hs_filter_pair_mismatch`、`hs_filter_other`：候选 gate 拒绝分支统计。`raw_enqueued`、`raw_output`、`raw_drop` 为传输阶段计数；M1–M4 由 host parser 对实际 FRAME 记录分类。
- 固件计数是本次开机以来的累计值；烧录后先重启再开始单一串口采集，便于直接读取本轮计数。`MODE_ACK` 不会清零计数。

### 2026-10-26 诊断固件烧录与被动 sanity

- 最终诊断app已烧录COM10并通过esptool写入哈希校验，app SHA256 F6AD6F647F609D5B7A6BDA661B345CC471BCD9F1E5BE76569AD46B141ACCD43D（906,976 B）。
- 12秒被动 channel 2 sanity：CSI callback 570，目标有效 CSI 48；prom_data 64、目标相关Data 5、pair_seen 5。queue/raw/CSI drop、UART写错误、截断、payload missing与empty CSI均为0，最低heap 111,940 B。MODE STOP/FINAL正常，COM10释放。
- 仅验证诊断固件运行及目标CSI callback；未开始HANDSHAKE_ONLY断开/连回。详细匿名结果见结果目录的2026-10-26被动CSI sanity报告。

### 2026-10-26 HANDSHAKE_ONLY 单次人工断开/连回漏斗

- 诊断统计：prom_data=658，target-related=63，exact pair=63（59上行、4下行）；63个均为Protected，unprotected=0。长度<=256B为61、>256B为2；pair_small/LLC-SNAP/0x888e候选均为0；Protected拒绝63，其他拒绝0。
- raw_enqueued/output/drop=0；M1/M2/M3/M4=0。CSI callback 6128、目标有效CSI 453；queue/写错误/truncation均0，最低heap109336 B。不能证明缺失握手帧曾到达promiscuous callback，因此本轮不改筛选器。
- 完整匿名漏斗与边界见[诊断筛选漏斗报告](../结果/real_poc_8da_diagnostic_filter_funnel_20261026.md)。

### 2026-10-26 CSI callback / promiscuous 路径审计

- 先前成功抓到的M3是promiscuous callback产生的FRAME（record_serial=120）；该capture没有CSI_DATA。
- ESP-IDF 5.5.5 CSI API含`hdr/payload/payload_len/mac/dmac/rx_seq`。HANDSHAKE_ONLY在计数有效CSI后提前return，因此不是API缺字段；当前回调仅保留Jetson→AP方向。
- 12秒sanity曾产生一条未截断的Protected CSI_DATA（payload 97/97、CSI 114/114），证明同一记录可承载Protected帧与CSI；尚未完成解密或packet_id恢复。建议将CSI-centric atomic record作为业务关联主线，不再要求promiscuous负责全部Data配对。
- 双向CSI回调EAPOL捕获、CSI_DATA的host EAPOL解析和Protected packet_id解密仍待验证。详见[CSI callback路径审计报告](../结果/real_poc_8da_csi_callback_path_audit_20261026.md)。
