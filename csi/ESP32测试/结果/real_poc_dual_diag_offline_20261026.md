# HANDSHAKE_DUAL_DIAG 离线源码审计、实现与构建

日期：2026-10-26

## 结论摘要

- **25925 条目标 pair CSI → 0 条 CSI_DATA 的直接原因已从当前源码确认：**上一轮 `HANDSHAKE_DIAG` 调用 CSI 路径时传入 `eapol_only=true`。CSI callback 先以 FC bit 14 判断 Protected；Protected 帧在 `diag_reject_protected++` 后立即 return。该轮 25,925 条目标 CSI 全部被计为 Protected，所以它们都在 CSI_DATA 入队之前被模式 gate 拒绝。不是已知 queue、UART、host、PCAP 或 tshark 丢失。
- 这不说明空口没有 EAPOL，也不说明 promiscuous callback 同期看到的 2,366 条目标相关 Data 中有没有 M1–M4；该模式只留下聚合统计，没有逐帧 FRAME。
- **采用双路径：**promiscuous 仅输出目标 pair 的 clear EAPOL 握手候选；CSI callback 输出目标 pair 的有效 Protected/clear frame bytes + CSI atomic `CSI_DATA`。握手不必来自 CSI callback，二者不做跨 callback join。
- 新 `HANDSHAKE_DUAL_DIAG` 已完成离线测试及 ESP-IDF build，**尚未烧录**。没有 Jetson、ESP、COM10 或实机网络操作；新代码的现场行为仍未知。

## 本轮读取与审计范围

审计对象包括本地 8d 分支 `main/capture_core.inc`、`main/staged.c`、host decoder/parser、`capture_csi_diag.py`、`wpa2_gate8c.py`、已有 `decrypt_probe8.py`，以及本地 ESP-IDF 5.5.5 CSI 类型定义和 2026-10-26 HANDSHAKE_DIAG 公开汇总。私有原始采集仍留本地，本报告不复述 MAC、SSID、IP、EAPOL nonce/MIC 或 Protected payload。

### 两条路线的工程取舍

| 维度 | Promisc握手 + CSI_DATA业务帧 | 所有材料必须来自 CSI callback |
|---|---|---|
| 可实现性 | 现有 promisc FRAME parser 可识别 EAPOL-Key；历史真实 M3 已从该路径被识别。CSI callback 已有 frame/payload/CSI 原子记录能力 | CSI callback也提供 `hdr/payload/payload_len/rx_seq/buf/len`，技术上可分类 clear EAPOL；但最新 HANDSHAKE_DIAG 没有任何 CSI_DATA，且该统计主要反映模式过滤条件 |
| 对最终PoC的影响 | 只要握手能供 tshark 解密、业务 Protected frame和 CSI 留在同一条 CSI_DATA，就足够恢复 packet_id 并绑定 CSI | 不提升最终 packet_id↔CSI 正确性，却增加握手必须被 CSI API 回调并通过同记录 CSI gate 的依赖 |
| 判断 | **推荐并已实现为 DUAL_DIAG** | 不作为架构要求；仍保留 host CSI_DATA EAPOL parser供诊断 |

真实 M3 来自 promiscuous FRAME（serial 120），不是 CSI_DATA。完整四次握手、MIC/CCMP检查、密码解密和业务 packet_id仍未验证。

## HANDSHAKE_DIAG 返回链与 Protected bit可信度

CSI路径的有效执行顺序如下：

1. `csi_cb` 仅在 STOP 状态早退；诊断模式不要求 `wifi_csi_info_t.mac == target`，交给 `csi_diag_cb` 从 header筛选。
2. `csi_diag_cb` 复制 `p->hdr` 前24字节，依 FC 类型/子类型推导 802.11 Data header长度；无 header、长度不是24–36、或完整header长度不一致时布局拒绝。
3. 以 header FC 的 ToDS/FromDS 与 RA/TA 判断 exact Jetson↔AP pair；非目标 pair直接返回。CSI callback两方向均可进入诊断。
4. 计数 `rx_channel_estimate_info_vld`、`rx_state` 与有效 CSI；HANDSHAKE_DIAG 在之后继续检查 Protected。
5. `uint16_t fc=le16(hdr)`，`fc & 0x4000` 作为 Protected；在 `eapol_only` 路线中如果为真立即 `diag_reject_protected++` 并返回。
6. 对 clear 候选再要求 `payload_len <= 256`、payload非空；握手专用模式排除fragment/A-MSDU；要求 `payload` 指针位于 header范围内、overlap bytes吻合、满足 LLC/SNAP、EtherType `0x888e`；最后检查完整记录不超过 CAP，再取队列slot并同一回调复制 metadata/header/payload/CSI。
7. 对历史 HANDSHAKE_DIAG，CSI buffer失效并不是硬门槛，目的是允许“frame有效但 CSI无效”的 EAPOL诊断记录，并通过有效位标识 CSI。不过前面的 Protected gate已足以解释本次 25,925→0。

**FC/Protected bit判定等级：高可信推断，但不是独立原始帧确认。** 本机 ESP-IDF 5.5.5 `wifi_csi_info_t.hdr` 字段注释称其为 Wi-Fi packet header；IDF公开类型提供 pointer 与 `payload`，但注释未逐字保证 `hdr[0..1]` 一定为未变换 raw MPDU FC，也未给出 hdr buffer长度字段。当前代码按标准 FC bit14与标准 header地址偏移读取，并在大量 CSI 记录中持续匹配出 exact pair，且独立 host decoder会再次核对 FC/TA/RA 与wire metadata。QoS只改变 header长度，不改变 FC 的前两字节，因此不会移动 Protected bit。

仍缺少“与该 CSI callback 对应的独立 raw MPDU”逐字节对照，不能把 FC 解释写成 API 已明文保证。新 DUAL 记录完整复制同一次 callback 的 hdr/payload/rx_ctrl/CSI，host 校验重叠区间和FC/address metadata，可现场验证内部一致性；promisc EAPOL则提供另一条辅助观察。

## 两模式比较：25925为何变成0

| 条件 | 被动 PROBE sanity | HANDSHAKE_DIAG | 是否解释0 CSI_DATA |
|---|---|---|---|
| pair筛选 | 普通CSI输出先要求 `p->mac`为target，随后核对 header TA/RA | 按header DS位与RA/TA筛双向 exact pair，不要求 `p->mac`等于target | 本轮exact pair CSI计数已到25,925，非主因 |
| Protected | PROBE正常 CSI_DATA不因Protected被拒绝 | `eapol_only`看到 Protected就立即return | **是。本轮25,925条全部Protected，故全部挡在入队之前** |
| payload长度 | 长度/record容量 gate；超出256通常不输出 | EAPOL路径也限制 API payload≤256 | 可能过滤其他帧，但本轮明确的首要降零 gate是Protected |
| frame/layout | 基于该callback自带的 header/payload，按现有 atomic记录校验 | overlap、LLC、EtherType等 EAPOL候选条件 | 本轮Protected return发生在这些payload候选检查之前 |
| CSI条件 | 需要有效 CSI和可用buffer才能输出普通 CSI_DATA | 即使帧有EAPOL也可能标记CSI无效；新 DUAL则要求有效CSI | 本轮队列/输出条件未执行 |
| 入队和transport | 成功输出大量CSI_DATA；历史sanity queue/UART均0 | 0条CSI_DATA入队/输出；本轮drop/UART/truncation均0 | 不支持queue/UART解释 |
| Host/PCAP/tshark | 对已落盘CSI_DATA解析 | 输入没有FRAME/CSI_DATA，故没有EAPOL输入 | 不支持host/PCAP/tshark为本轮首个丢失层 |

从源码证据看，最早且充分解释本轮 `CSI callback → CSI_DATA` 零数量的层是**模式中的 Protected gate**。不能由此推出该空口窗口里的 M1/M2/M4 存在或不存在。

## DUAL_DIAG实现

### Promiscuous：受控 EAPOL RAW

- 继续使用原 full promiscuous filter；不重开“为什么full filter有效”的研究。
- 只对 valid Data header继续处理；先累计 target-related，再要求 exact STA/AP RA/TA及对应 ToDS/FromDS方向。
- 统计pair方向、clear/Protected、长度、LLC/SNAP、EtherType `0x888e`、EAPOL candidate、RAW enqueue/output/drop/truncation。
- 只有 clear、未fragment、非A-MSDU、LLC/SNAP且EtherType `0x888e` 的帧才尝试入队；Protected背景TCP ACK、其他protected小包、第三方帧及目标clear非EAPOL只统计/拒绝，不进入RAW queue。
- EAPOL捕获长度可到RAW `CAP`；过大时记为raw truncation拒绝，不伪装完整。

### CSI callback：Protected frame + CSI atomic

- 双向用 FC DS位、RA/TA选择 exact pair；不是 `mac` 字段单独过滤。
- 统计 pair、方向、Protected/clear、payload是否存在、长度分布、LLC/SNAP/EAPOL特征、CSI有效/无效、layout拒绝、入队/输出/drop。
- 不要求clear或EAPOL；不检查业务Protected payload内容，不做跨 callback join。
- 仅导出有效 CSI、非空 payload≤256B，且pointer delta/overlap验证通过、记录总量在CAP内的记录。Protected Data保持加密字节，与同一个CSI记录一起复制。
- 因此 CSI_DATA payload阈值适用于本轮低流量诊断，也覆盖计划中的48B CSID UDP；更大业务帧需要后续另行评估过滤覆盖，不提前放宽。

### 200 ms时间桶

- 固件用原子计数器把prom target-related/pair/up/down/clear/Protected/EAPOL/raw、CSI pair/up/down/clear/Protected/valid/payload/queue/drop及write errors聚合。
- 输出 nominal 200,000µs bucket，同时带实际 start/end/span 与 bucket id；调度延迟造成的实际桶宽会如实显示，不伪称精准定时。
- 每秒另有累计 DUAL_STATS；STOP时flush最后一个部分桶。host检查bucket id与时序连续性，便于看重连瞬间约500ms内prom EAPOL和CSI是否同时出现。

## Host与WPA2解密准备

- `wire8c.py`解码 FRAME、CSI_DATA、TIMELINE和控制记录；CSI_DATA重建验证header长度、指针overlap、完整payload、metadata与frame FC/地址一致。
- `wpa2_gate8c.py`保留 FRAME/RAW parser，并对CSI_DATA重用相同clear EAPOL-Key M1–M4分类；输出方向、Key Info、replay counter、record serial/rx_seq与CSI同记录状态。Protected business payload不能作为clear EAPOL解析。
- `capture_csi_diag.py --mode HANDSHAKE_DUAL_DIAG`只通过COM10接收ESP UART，最长300s或本地stop-file停止；不连接/修改Jetson。正常STOP/FINAL后调用私有离线analyzer，汇总frame来源、M1–M4、CSI_DATA方向/Protected/CSI有效性、时间桶、drops与transport。
- analyzer调用既有`wpa2_gate8c.convert()`生成private PCAP/handshake文件。原始CSI bytes、完整EAPOL nonce/MIC/握手frame和PCAP都只留私有capture目录；自动生成的私有文件不得提交或上传。
- `decrypt_probe8.py`已有使用本机预先配置Wireshark/tshark profile的WPA2解密入口，并要求完整连贯4-way及资源门禁，再将Protected CSI_DATA中恢复出的CSID与sender/receiver日志核对。无需重搜或重建profile；但本机完整真实握手/CCMP解密及packet_id恢复仍未在本阶段验证。

## 离线验证

- Python unittest：62项全部通过。覆盖target clear EAPOL M1–M4、第三方/非EAPOL/protected ACK排除、QoS与非QoS、ToDS/FromDS、CSI Protected业务记录、malformed/truncated/empty/overlap拒绝、host M1–M4、时间桶、5000个Protected背景候选不进RAW，以及一次完整合成stream→private analyzer/PCAP摘要流程。
- Python工具语法检查：全部当前`tools/*.py`通过。
- 既有C主机协议/static测试包含在上述61个先前测试中；本次新增 analyzer integration test 后总数为62。
- ESP-IDF 5.5.5 / Python 3.11.2 / `PYTHONUTF8=1`，ASCII临时构建副本的六个核心源/配置文件build前SHA均与本地输入一致。app大小 `917,376` bytes（最小app分区剩余约13%）。
- app SHA-256：`829F6C805E4067C3D7650CD4772C2BCD5B3933E67E1CFCC4134003D82E4C5D7D`。这仅是本次build产物哈希，不是已烧录或实机运行版本证明。
- `activate.py --export`因安装树缺少IDF constraints文件而未能通过依赖激活；未安装软件包。随后以已选择的Python 3.11.2、`idf_tools.py export`生成的本机工具PATH直接运行 `idf.py build` 成功。构建输出有既有 UART VFS API deprecated warning，不影响成功。
- 有两处源码宏错误曾被首次C编译捕获，已修复：JSON metric macro多余逗号与Windows `uint32_t` 对 `%u` 参数类型不一致；最终build通过。

## 下一次现场顺序

1. 由现场人员确认Jetson仍在原2.4GHz/channel 2；Codex不切网、不SSH重关联。由于新build未烧录，先决定是否将该app-only候选烧录；本轮没有烧录授权/设备条件。
2. 如果烧录，先做12s PROBE被动sanity：实读channel=2、target valid CSI>0、目标CSI_DATA>0，并要求queue/raw/CSI drop、UART/write、truncation、parser/CRC errors为0。失败即停，不断开Wi-Fi。
3. sanity通过后ARM `HANDSHAKE_DUAL_DIAG`，确认MODE_ACK与CSI继续增长。
4. 若需握手，用户在Jetson本机手动完成唯一一次断开/恢复，保持eth0不动；连接回来后观察10–20秒，停止采集。不远程reassociate、不自动retry。
5. 先检查自动生成的私有summary和timeline，再检查M1–M4来自FRAME或CSI_DATA、以及CSI_DATA Protected数据。结果不够就停止，不同轮重复断连需另行安排。
6. 只有真实可用握手材料通过本机tshark decryption profile检查后，才进入20个48B CSID UDP与sender/receiver日志关联。

## 最小 packet_id↔CSI成功门槛

至少一个发送 `packet_id=N`：

1. Windows receiver收到并CRC校验正确；
2. ESP CSI callback输出包含对应Protected业务frame的 CSI_DATA；
3. 本机tshark解密该条记录并恢复同一 CSID、run_id、packet_id=N；
4. 解密前该 CSI_DATA 自身带有效 CSI（有效标志、rx_state及必要的first-word检查均通过）。

不要求20/20成功，不假设UDP/MPDU/CSI是一对一。达到上述条件才声明最小PoC通过。

---
