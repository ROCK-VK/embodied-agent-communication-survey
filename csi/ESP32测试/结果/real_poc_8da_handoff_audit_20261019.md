# 8d-a 接管只读核验

核验日期：2026-10-19。范围为本地规则、日志、源码、Git、四轮 real_poc 落盘、build 目录和只读连通性检查。没有 build/flash、修改 ESP/Jetson、reassociate、发 UDP 或做现场解密。

## Git 与源码归属

- 发布仓库分支为 `main`；本地 HEAD、`origin/main` 与 GitHub `main` 均为 `001ea4495a3b432bbba7b268329ee9fa70cb83f3`。公开仓库工作树干净，`git fetch origin main` 成功。
- `001ea44` 是 8d-a full promiscuous filter 与两轮被动 CSI 验证的已发布提交。四个 `real_poc_8da_*` 新结果及下列后续工作区代码差异均未进入该提交。
- 实验工作目录本身不是 Git 仓库，因此不能用它的 `git status` 判定“无本地改动”。我将当前本地文件与公开 HEAD 的白名单副本逐个比较：`staged.c` 相同；`capture_core.inc`、`capture_real8c.py`、`wpa2_gate8c.py` 有后续差异；`orchestrate_real_poc.py` 只有本地副本、未发布。
- `capture_core.inc` 的本地差异新增 `HANDSHAKE_ONLY && n<=256` 的 pair-small 备用导出；没有检查 Protected 位。`is_eapol()` 仍独立识别 EAPOL，只有 `eapol` 与 `pair_small` 都为假时才返回，因此新增保护条件应只限制备用诊断分支，不能包住或删除 EAPOL 分支。
- `capture_real8c.py` 增加期望固件标签参数；`wpa2_gate8c.py` 改为即使 FRAME 未解析成 EAPOL也保留其PCAP索引。后者便于审计普通帧，但这些差异仍是未发布本地修改。
- 本地 orchestrator 使用 `range(1,5)` 自动执行最多四次 reassociate，每轮观察25秒后可重试；SSH连接默认超时15秒，循环没有覆盖整次实验的总时限。脚本还含本地认证材料，不应复制或发布。它目前不能用于实机。

## 四轮原始结果复核

| 本地结果目录 | 目标有效 CSI | 结构解析到的 M1/M2/M3/M4 | RAW 队列 | 结束状态 |
|---|---:|---:|---|---|
| `real_poc_8da_20261019_185414` | 173 | 0/0/0/1 | drop 0 | STOP/FINAL，握手不完整 |
| `real_poc_8da_20261019_190157` | 247 | 0/2/0/2 | drop 0 | STOP/FINAL，握手不完整 |
| `real_poc_8da_20261019_190916` | 514 | 0/3/0/5 | drop 0 | 没有 STOP/FINAL；sidecar 仍显示 HANDSHAKE_ONLY，记录不完整 |
| `real_poc_8da_20261019_192402` | 547 | 0/0/0/0 | output 442，raw_drop 508 | `resource_gate` 后 STOP/FINAL，队列清空、RF关闭 |

四轮均未形成完整、连贯的 M1-M4；也没有进入 PROBE、UDP 或 WPA2 解密。结构分类不等于 MIC 密码学验证。HANDSHAKE_ONLY 不导出 CSI_DATA 是设计行为；第四轮的 `csi_total=4089`、`csi_target_valid=547`、`rx_ht=1572` 说明 CSI 接收仍在工作。

第四轮 stream 解码得到442条落盘FRAME，逐条检查802.11 Frame Control后有441条Protected Data、1条clear Data；442条都不超过256B，EAPOL parser对它们均未接受（441条因不是完整clear EAPOL MPDU被拒，1条不是LLC/SNAP EAPOL）。底层计数为 `raw_enqueued/raw_output=442`、`raw_drop=508`、`csi_drop=0`、`queue_drop=508`、高水位24/24、最低空闲heap 29,512B。首次报告非零drop的STATS在ESP单调计时约54.296秒；随后STOP/FINAL显示RF已关闭。

这支持“宽泛 pair-small 备用导出使RAW队列饱和并触发resource gate”这一判断：本地源码会把所有匹配AP/Jetson且长度不超过256B的Data送入该队列，不论Protected位。但被丢的508条没有逐帧保存，因此不能断言每一条都是Protected背景流量，也不能声称M1-M4因队列爆仓全部丢失。第四轮heap高于16KiB门限，当前数据更直接指向RAW drop，而不是低heap触发停止。

## 重关联时序证据

- 已保存的real_poc目录只有ESP串口stream、state/ready/summary、commands；未找到Gemini的独立stream分析报告、该轮Jetson journal/wpa_supplicant日志或记录 `wpa_cli reassociate` 调用次数的orchestrator stdout。
- “全频段扫描约11秒、约12秒回到信道并完成握手”只出现在orchestrator源码注释，本轮无法用Jetson日志佐证。四轮目录各自的EAPOL结构数据不等于reassociate命令数，实际总次数未知。
- 当前只读检查中，Jetson ping不通、TCP/22不可达，单次SSH连接在认证前超时；因此当前Wi-Fi关联状态和本轮 `journalctl` 无法确认。不能把历史channel 2的CSI采集结果当作现在仍在线。

## 固件与设备当前状态

- 最近四轮的 `READY.version` 都报告 `sniffer-8d-a-full-filter`。这是固件自报标签，不含源码或应用hash。
- 8d-a已发布基线manifest的source/build hash与当前本地 `capture_core.inc`、独立8d-a build目录中的bin/ELF不同。当前本地源码修改时间早于该build输出；四轮采集晚于build，但没有找到新manifest或flash hash readback。结果表现与新增pair-small路径一致，仍不足以证明运行镜像与当前文件逐字节相同。
- 当前没有采集/orchestrator进程；Windows未枚举COM10，不能读取板上现状。IDF 5.5.5、Python环境和build目录存在，离线build工具可用；当前无法确认串口烧录条件。

## 接管后的下一步

等待用户确认后，先对本地 `pair_small` 做最小收紧：HANDSHAKE备用诊断帧要求严格AP/Jetson pair、Protected=0、长度不超过256B；独立 `is_eapol()` 分支仍照常入队，确保有效EAPOL不受该过滤影响。离线测试覆盖Protected小帧拒绝、clear小帧候选、EAPOL单独放行，再构建并记录新manifest。

烧录必须等COM10重新枚举并核对source/build。烧录后先执行约10秒被动CSI sanity，未过门禁即停止。后续任何reassociate前先单独汇报ESP ARMED、CSI、SSH和Wi-Fi状态，取得该次明确确认后只执行一次，最长等待约30秒；旧orchestrator修正前不得运行。
