# sniffer-8d CSI-centric：当前 OPEN_AP_POC / 历史 DUAL_DIAG

更新：2026-10-28。当前唯一推进的实机目标是 Open SoftAP 明文 UDP → 同记录 CSI_DATA；不再开展 WPA2 handshake/M1–M4 捕获。

## 当前：OPEN_AP_POC（首轮 app-only 烧录成功，ESP-only sanity 未通过）

- 独立模式 `OPEN_AP_POC`；原 `PROBE`、`HANDSHAKE_DIAG`、`HANDSHAKE_DUAL_DIAG` 保留。
- 运行时命令 `CFG_OPEN_AP,2,<SSID>` 配置 2.4 GHz、channel 2、HT20、`WIFI_AUTH_OPEN` SoftAP；SSID 默认 `CSI-C5-OPEN-POC`，不保存到 NVS。ESP UDP receiver 监听端口 39001。
- 关联 station 后根据 AP 事件确定目标 MAC；CSI callback 只导出 AP 与已关联 station 的有效 CSI 原子记录，保留 header/payload/CSI，并统计方向、Data/QoS、Protected/clear、CSID与队列/传输健康。
- 复用 `udp_probe_protocol.py` 里的 48-byte CSID payload。ESP socket CRC-valid UDP_RX 是接收侧 ground truth；host 只有从同一条有效 CSI_DATA 恢复到相同 `run_id/packet_id` 才给出 PoC PASS，不用时间或序号猜测。
- Jetson发送：`python tools/send_open_ap_probe.py --destination <ESP_AP_IP> --run-id <整数> --output <私有目录>/sender.jsonl`。默认20包、150ms间隔，可用 `--count` 降至1–20；每次运行使用新日志路径。
- ESP UART采集：`python tools/capture_open_ap_poc.py --port COM10 --stop-file <私有目录>/STOP --output <新的私有目录>`。工具将自动配置SoftAP并ARM，最多300秒；它不会改Jetson网络，也不会发业务UDP。只在用户现场确认后才手动切换Jetson。
- 离线验证：完整 Python unittest运行77项，76项通过、1项跳过；Open AP专项9项全部通过；4个新增Python工具 `py_compile`通过。IDF 5.5.5/Python 3.11.2 build成功，app 963,984 bytes，SHA-256 `312238DB6B43134EF8AE2CAAE77723C07D114CC0C29AA5316CFDBCA26F3A34FA`。
- 首轮现场：app-only写入`0x10000`并经esptool校验。收到 `CFG_OPEN_AP` 后出现 `ESP_ERR_WIFI_NOT_STARTED (0x3002)`；没有获得 `OPEN_AP_READY`、channel/BW读回或UDP server ready。错误输出缺少源码行号，具体API尚未确认。详情见[首轮 ESP-only sanity结果](../结果/open_ap_poc_esp_sanity_20261028.md)。本轮到此停止，没有Jetson切网、没有发送UDP，也没有CSI_DATA/packet_id结果。
- 下一步：先离线核对SoftAP初始化中Wi-Fi启动状态要求，修复后重新做build；新的ESP-only sanity需另行安排。只有Sanity通过后才告知用户并等待其明确确认，再由用户手动切Jetson USB Wi-Fi；不自动重试。Jetson `eth0`、ROS/DDS、Go2/MID360 不操作。

构建与边界见[Open AP离线实现与构建报告](../结果/open_ap_poc_offline_20261027.md)。

---

## 历史：sniffer-8d CSI-centric DUAL_DIAG（当前不再执行）

ESP32-C5 / ESP-IDF 5.5.5。当前源码候选保留同一条 CSI callback 原子记录路线；HANDSHAKE_DIAG 现场结果显示它只接受 clear EAPOL，而最近 25,925 条目标 pair CSI 全部是 Protected，因此按旧模式条件在 CSI_DATA 入队前返回。该结果没有证明空口不存在 EAPOL。

新增 `HANDSHAKE_DUAL_DIAG` 用两条 callback 各做一件事：

| 路径 | 责任 | 导出条件 |
|---|---|---|
| Promiscuous | 提供握手帧材料，输出为 `FRAME` | 精确 Jetson↔AP pair、clear、未分片、非 A-MSDU、LLC/SNAP 且 EtherType `0x888e`；Protected 背景流只计数，不进入 RAW 队列 |
| CSI callback | 提供最终业务 frame↔CSI 原子记录，输出为 `CSI_DATA` | 精确 pair 双向；CSI 有效；API payload 非空且不超过256B；header/payload 指针重叠布局一致；整条记录不超过缓冲容量。Protected 与 clear frame 都可保存 |

两条路径不做跨 callback frame join。为完成 packet_id↔CSI，EAPOL 不要求来自 CSI callback：promiscuous 可提供 WPA2 解密所需握手，CSI_DATA 则必须把 Protected 业务帧和有效 CSI 放在同一记录内。历史 M3 确实来自 promiscuous FRAME；完整 M1–M4、解密和业务 packet_id 尚未验证。

## 历史 DUAL_DIAG 离线验证状态

- `HANDSHAKE_DUAL_DIAG`、双向 pair 过滤、受限 EAPOL RAW、Protected CSI_DATA 原子入队及时间桶代码已加入本分支。
- 每200ms目标 pair 的聚合时间桶记录 promisc/CSI方向、clear/Protected、EAPOL、入队/导出与 drop计数；实际 start/end/span 随记录导出。另有累积 DUAL_STATS 和 STOP 时最后一个部分桶。
- `capture_csi_diag.py` 可限时采集并保存 TIMELINE；收到正常 STOP/FINAL 且传输完整后调用 `analyze_dual_diag.py`，离线统计 FRAME/CSI_DATA 的 M1–M4来源、方向、serial/rx_seq、CSI有效性和受保护CSI数据。原始 stream、转换PCAP与握手明细均只保存在本机。
- 本地 ESP-IDF 5.5.5 / Python 3.11.2 build 成功。2026-10-27 app-only 烧录候选固件并通过 esptool 写入校验；PROBE sanity 目标有效 CSI=43、CSI_DATA=1。之后一次限时 DUAL_DIAG 手动断开/恢复捕获到641条目标pair CSI、80条有效CSI_DATA和1条FRAME M1，M2/M3/M4未识别；所有drop、截断、串口错误为0。
- 离线回归共62项通过，包含过滤条件、双方向、QoS/非QoS、受保护业务帧、EAPOL M1–M4分类、错误/截断处理、时间桶和完整 host analyzer 合成流测试。Python工具语法检查通过。以上都不是实机握手或解密证明。

## 旧版 DUAL_DIAG 现场流程（历史步骤；当前不执行）

2026-10-27这轮唯一一次手动断开/恢复已完成；下面步骤仅供后续单独安排的采集使用。先在本地安全环境把 `$TargetMac` / `$ApMac` 设为现场确认值，不要写进公开日志；以下仅为流程示意。

```powershell
$SanityDir = "<本地私有目录>\sanity_<唯一名>"
python tools/capture_csi_diag.py --port COM10 --channel 2 --target $TargetMac --ap $ApMac --mode PROBE --duration 12 --output $SanityDir
```

本轮 PROBE sanity 已满足上述门槛；下次只需重新读回 channel 2、CSI及错误计数，然后可运行：

```powershell
$RunDir = "<本地私有目录>\dual_diag_<唯一名>"
$StopFile = Join-Path $RunDir "STOP"
python tools/capture_csi_diag.py --port COM10 --channel 2 --target $TargetMac --ap $ApMac --mode HANDSHAKE_DUAL_DIAG --max-duration 300 --stop-file $StopFile --output $RunDir
```

确认 DUAL_DIAG 已 ARMED、channel 2及目标 CSI持续正常后，才由用户在 Jetson 本机手动断开并连回一次；连接恢复后观察约10–20秒，再创建 stop-file 结束采集。工具不操作 Jetson，不远程重关联、不自动重试，最长300秒后自动停止。采集结束后先读自动生成的私有报告；无论是否得到握手，都不在同一轮重复断连。

本次烧录与 PROBE sanity 见[固件sanity结果](../结果/real_poc_dual_diag_flash_sanity_20261027.md)；DUAL_DIAG单次人工断开/恢复结果见[实机报告](../结果/real_poc_dual_diag_manual_reconnect_20261027.md)。

## 历史路线：WPA2解密阶段门槛（已被 Open AP PoC 路线替代）

需要先有可用于 tshark 的真实、连贯 M1–M4，并确认其目标方向和 Key 信息；这只是握手分类，仍需由本机既有解密 profile 完成私有解密检查。之后再发送20个48B CSID UDP，保留 sender/receiver CRC日志；对同轮 CSI_DATA 做解密和关联。至少一个 packet_id 与发送、接收记录一致，且其对应同一 CSI_DATA 含有效 CSI，才算最小 PoC 成功。不假设一个 UDP 必定对应一个 Wi-Fi frame 或一个 CSI。

所有 MAC、SSID/PSK、nonce/MIC、原始 FRAME、Protected payload、PCAP、SSH/现场地址与解密结果均不得公开。旧 FRAME parser 保留作辅助；full promiscuous filter 保持既有设置，不再研究其根因。

详细实现、过滤原因分析、build SHA及限制见[DUAL_DIAG离线审计报告](../结果/real_poc_dual_diag_offline_20261026.md)。

---

以下为原8d-a full-filter诊断阶段的历史记录；full promiscuous filter 仍保持不变，但它不再是 CSI_DATA 握手/业务关联主路径。

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
