# 树莓派4B Nexmon CSI测试方案

整理：2026-10-14。状态：官方支持、维护者说明与当前Makefile已核对；以下步骤待执行，尚未登录/安装/测试本项目树莓派。另一条路线见[ESP32测试](ESP32_CSI测试方案.md)。

## 执行前版本门禁

针对新购Pi4B和专用SD卡，**首选Raspberry Pi OS Lite 64-bit Trixie + #395/Makefile.rpi/vendor-command路线**。这是本项目部署选择，维护者支持说明不等于本项目复现成功；到货后先填写下表。

| 字段 | 执行前填写 |
|---|---|
| 硬件型号、无线芯片/revision | 待填；确认Pi4B和板载BCM43455系列 |
| OS image名称/日期/校验、32或64位、精确kernel | 待填，不用“最新系统”替代版本 |
| nexmon/nexmon_csi commit | 待填，固定两者并保存构建日志 |
| nexutil版本/构建方式、实际driver | 待填；主线USE_VENDOR_CMD=1，核对当前Makefile目标 |
| firmware路径/版本/SHA256、备份/恢复方案 | 待填；先保留原固件及测试卡 |
| 频段、信道/带宽、core/stream、TX MAC | 待填，按本次测量填写 |
| 当前管理路径 | 待填；稳定有线管理Pi先于Wi-Fi固件变更 |
| 准备/编译/运行结果 | 分开填写，纯编译成功不等于CSI采集通过 |

门禁：**硬件/版本/有线管理确认 → 固定仓库与工具链 → 纯构建并保留日志 → 核对固件及恢复 → 再在专用测试Pi安装/配置 → 基线采集**。不执行Jetson修改，不混用新旧monitor步骤。旧4.19/5.4/5.10 modified-brcmfmac只作fallback。

## 1. 目标与首选拓扑

层级保持：基线CSI → 普通第三方Wi-Fi TX → Jetson RTL8821CU → packet_id/sample_id关联 → 最后D435i/MID360/位姿。先取得可解析、来自指定TX的CSI，不把精确业务关联前置为基线门槛。Pi作为固定监听节点，不优先把它当同时运行普通AP、UDP接收和CSI的网关。

```text
Jetson RTL8821CU --Wi-Fi上行--> 现有/测试AP --> Windows或业务服务器
           \--同信道无线监听--> Pi4B板载Wi-Fi（Nexmon CSI）
Windows --有线网络--> Pi4B eth0（SSH管理）
```

监听Pi不加入业务转发路径，且不能把AP→服务器的有线流量当测量链路。Pi管理网口是Pi自身eth0，**不是Jetson承担Go2/MID360的eth0**。本轮没有接线、改AP/信道或发包。

此拓扑有机会保留Jetson现有Wi-Fi/SSH，但CSI与业务packet_id关联难度更高；第一轮只证明目标上行CSI，之后再解决原始帧/业务记录的对齐。

## 2. 官方支持与版本选择

[项目支持表](https://github.com/seemoo-lab/nexmon_csi)列出Pi4B的bcm43455c0、patch基准firmware7_45_189；能力为a/g/n/ac及最高80MHz。树莓派板载Wi-Fi走SDIO，不以安装USB无线网卡代替目标芯片；现场还需核实真实板卡和无线设备。

重要更新：[维护者教程#395](https://github.com/seemoo-lab/nexmon_csi/discussions/395)提供较新Raspberry Pi OS内核的Makefile.rpi/vendor-command方案，并在2026-07回复确认Pi4B可用。2026-09又修正了Makefile；维护者2026-07对Pi4B回答可用，对Pi4B+Trixie表示教程无需针对4B修改。因此新购板/专用卡采用Lite64-bit Trixie与#395主线；到货后记录精确image/kernel并验证，不能保证任意最新系统一键成功。

| 路线 | 使用条件 | 处理原则 |
|---|---|---|
| Raspberry Pi OS Lite64-bit Trixie + Makefile.rpi（首选主路线） | 核对实际OS/架构/driver、工具链与vendor-command；有独立有线管理 | 跟维护者教程、当前Makefile，记录可复现组合 |
| 旧4.19/5.4/5.10 + modified-brcmfmac（fallback） | 实验室已有验证的旧镜像与工具链 | 跟README相应分支；不能混用新路线命令/恢复方法 |

当前资料快照：nexmon=`68720406f54ff16cad28fd3c51f2392aefad9fb7`；nexmon_csi=`1232edf2cf1e7ae0561676c49e4dd4eb22c8a27e`。是2026-10-14读到的版本，不是本项目实测通过版本。

[当前Makefile.rpi](https://github.com/seemoo-lab/nexmon_csi/blob/1232edf2cf1e7ae0561676c49e4dd4eb22c8a27e/Makefile.rpi)重载目标用brcmfmac_cyw。教程文本与旧镜像可能仍提brcmfmac/brcmfmac_wcc；先读实际driver和所选Makefile，不把名字强改到相似版本。

## 3. 准备与只读盘点

准备Pi4B、可靠电源、测试microSD、网线和有线SSH管理；预留恢复SD卡/备份。现有板有用途时保留其系统，使用专用测试卡。电脑先确认通过有线能管理Pi，再操作Wi-Fi patch。

在Pi读下面信息并保存，接口名按实际情况替换；命令只用于Pi，不在Jetson执行：

```bash
cat /proc/device-tree/model
uname -a
uname -m
cat /etc/os-release
ip -br addr
ls -l /sys/class/net
ethtool -i wlan0
readlink -f /sys/class/net/wlan0/device
lsmod | grep -E 'brcmfmac|brcmutil|cfg80211'
ls /usr/lib/firmware/cypress /lib/firmware/brcm
```

必要时只读查看dmesg里的无线芯片/固件加载信息，记录实际driver、固件文件路径/链接/哈希。Pi4B身份与BCM43455系列芯片、patch基准需核对，不能仅凭商家标题。

## 4. 安装阶段（未来只在测试Pi执行）

新购测试板默认按已选择的Lite64-bit Trixie/#395主线准备；先用到货后的精确image/kernel、driver和工具链核对。只有明确的兼容障碍或已有验证旧镜像时才转fallback并记录理由，不重新设计路线。以下是步骤骨架，不是一键安装脚本；硬件/OS未知时不执行包升级、刷写或重载。

1. 在测试Pi记录系统镜像、现有firmware链接/哈希、nexutil来源及无线管理状态；备份测试卡。
2. 依照#395完成构建依赖和工具链准备。64位系统要处理32位工具链运行库；教程仍涉及Python2.7/旧库兼容，不能把它们装到Windows现有Agent环境或Jetson。若需引入旧软件源，先针对测试卡明确配置与恢复，不原样盲贴教程改apt源。
3. 获取并固定两个仓库版本；在nexmon根目录source setup_env.sh，完成其构建。可先做纯编译，编译错误保留日志，不尝试随机升级固件/内核解决。
4. 构建nexutil时使用USE_VENDOR_CMD=1（新路线）；确认命令确实是这个构建的版本。
5. 将nexmon_csi放在nexmon的patches/bcm43455c0/7_45_189/下，按所选版本用Makefile.rpi编译。
6. 仅在Pi已有稳定有线管理、固件备份、版本分支核对后，按Makefile.rpi执行install-firmware → unmanage → reload-full，再nexutil -m1。unmanage作用于测试Pi无线管理，不能扩大为默认停所有服务或卸载wpa_supplicant。它们会改变Pi无线状态，可能断无线SSH；严禁在Jetson上运行。

分支确定后的关键命令参考：

```bash
# 已完成工具链/依赖准备后，在nexmon根目录
source setup_env.sh
make

# 新路线的nexutil（在utilities/nexutil目录）
sudo -E make install USE_VENDOR_CMD=1

# 在patches/bcm43455c0/7_45_189/nexmon_csi目录
make -f Makefile.rpi
# 以下会改变测试Pi的Wi-Fi固件/连接，不能当只读命令
make -f Makefile.rpi install-firmware
make -f Makefile.rpi unmanage
make -f Makefile.rpi reload-full
```

capability赋予、实际固件路径、工具链依赖按已核对版本教程决定，本文件不为未知系统生成通用sudo安装脚本。旧内核分支不要套用这段。

恢复新路线的入口为同目录`make -f Makefile.rpi restore-wifi`，并核对firmware/管理状态；如失败，用备份测试卡恢复。卸载/恢复操作只作用于测试Pi，不改Jetson。

## 5. 第一阶段：指定TX的CSI基线

先用测试电脑/AP产生正常数据帧，Pi同信道监听；后续Jetson阶段可保留现有AP链路。第一次若用独立测试AP可先20MHz简化参数，再40/80；若直接监听现有149链路，不改Jetson或AP，按实际监听参数配置Pi。

Jetson已知MAC为<JETSON_MAC>、149/5745MHz，80MHz固定为高可信推断。这是10月13日快照，执行时只确认当前连接仍匹配，不继续追查带宽证明。不能写死旧快照永远有效。

nexmon_csi目录中构建utils/makecsiparams，先看帮助。下面是**配置测试Pi接收器的示例**：

```bash
# 在utils/makecsiparams目录
make
./makecsiparams -h
# 仅在监听参数仍是149/80、目标MAC仍正确时使用
./makecsiparams -c 149/80 -C 1 -N 1 -m <JETSON_MAC>
```

输出base64配置串，再按新路线的nexutil配置；以下占位符须用真实输出替换：

```bash
nexutil -Iwlan0 -s500 -b -l34 -v<本轮生成的base64配置串>
nexutil -Iwlan0 -m1
nexutil -Iwlan0 -m
nexutil -Iwlan0 -k
```

`-C/-N`是所选core/stream mask，不能把该示例写成多天线测量。初期不照搬README的`-b 0x88`帧过滤，先确认目标数据帧类型，避免把实际目标全过滤。MAC过滤核对无线帧Address2/TX地址，防止捕到AP转发的下行帧。

新方案按#395使用nexutil -m1启用芯片monitor、nexutil -m读回、wlan0抓UDP5500。维护者说明OS/iwconfig可能不知道固件monitor状态，不能据其仍显示Managed判失败。旧README创建mon0的方法不得混入主线。

采集专用Pi上生成的CSI UDP5500，限定时长，保存于Pi测试目录再复制回本阶段结果目录：

```bash
mkdir -p results/pi_trial_001
sudo timeout 60 tcpdump -ni wlan0 -s 0 -w results/pi_trial_001/csi.pcap 'udp dst port 5500'
```

这是**未来测试Pi抓包**，不是此前Jetson授权的10秒eth0抓包；本轮未执行。timeout结束码124通常只是到时结束，需检查文件/计数才判断采集成功。Pi3B+/4B的CSI导出抓wlan0，不抓mon0。

首轮只要有来自目标TX、可解析的非空CSI记录，再做5分钟连续采集和停目标测试发送的负对照；不要仅凭UDP5500有包就宣称Jetson样本关联完成。

## 6. 解析与质量检查

依据所固定版本的数据结构读取magic、发射MAC、原帧sequence、core/stream、chanspec和CSI数组。BCM43455的复数格式是int16实部/虚部；20/40/80MHz完整数组数量依配置，不等于所有点都有效。解析器先用仓库示例数据验证，避免读错旧magic/字段偏移。

Guard/DC以及模式不同的无效频点要标识，不把“中间部分低值”立即判驱动坏；可能是宽信道里的较窄帧。PCAP主机时间是导出/捕获时间，不自动等于原始无线接收时间或Jetson发送时间。

需统计：总CSI、目标MAC CSI、成功解析、错误长度、source/sequence变化、重复、间断、主机捕获丢失和保存文件大小。保存原始数据，不只保留曲线截图。

### CSI采集漏帧与相位边界

[#390](https://github.com/seemoo-lab/nexmon_csi/issues/390)中社区用户zeroby0解释PHY→处理器复制CSI期间接收可能存在空窗，并提醒iperf/UDP业务数不直接等于无线帧数；**该回复不是维护者回复**，本项目未验证机制/漏帧率。将漏CSI作为待测边界，不以“100%无线帧都有CSI”为通过条件，也不把差额一律归因无线丢包。

[#391](https://github.com/seemoo-lab/nexmon_csi/issues/391)中维护者jlinktu明确：bcm43455c0的CSI用于逐包均衡/信道估计，硬件不为连续包的phase continuity设计。因此基线验收以**CSI存在性、来源MAC、长度/chanspec、幅度合理性、持续采集**为主，不要求跨包绝对相位连续。相位研究需另做校准/限制评估，不能由基线曲线直接推出定位精度。

## 7. 第二阶段：普通UDP业务关联

候选拓扑保持Jetson STA→AP→业务接收电脑，Pi只监听Jetson→AP的无线帧。CSI包中的sequence不能直接等同业务sample_id；第三方TX先做正确来源CSI，Jetson先重复该来源检查，再进入精确/近似关联。本轮不改Jetson wlan0/eth0，不安装Jetson CSI驱动或接真实相机/雷达大流量。

业务包保持与ESP方案同契约：run_id、sample_id、packet_id、send_monotonic_ns、send_wall_ns、payload_kind；初期一条样本一包、约128–512B、单播到测试接收端。拟议1/10/50pps各5分钟；不发机器人控制入口，不做真实相机/雷达全量上传。

匹配需要两条证据链：

1. 原始无线帧→CSI：TX MAC、802.11 sequence control/TID/fragment、信道、时间窗口、重传/core/stream信息。
2. 原始无线帧→UDP packet_id：读取或解码该帧中的IP/UDP业务内容，并与接收端业务日志核对。

Nexmon CSI导出默认没有附上完整业务payload；仅靠MAC/sequence不足以得到packet_id。原始帧记录能否与CSI同时取得要作为单独试验，不默认新路线有可用mon0原帧抓取。加密Wi-Fi上监听payload还需可解码条件；先用自己的独立测试网络验证，不改实验室现有AP来规避问题。

若原始帧不可得/不可解码，只能按受控时间窗口、发送日志与接收业务包作近似关联，报告歧义/缺失，**不能把采集CSI成功写成逐包精确业务关联成功**。sequence会回绕，重传和聚合会产生非一一关系；每个run_id单独处理。

### 四种数量分别统计

| 数量 | 定义/取得方式 |
|---|---|
| 发送业务数 | TX日志中的实际业务packet_id及发送结果；发送尝试另列 |
| 原始Wi-Fi frame数 | 明确观察点/时间窗口的原帧记录，说明重传/分片/聚合；不可获取则写“未测”，不能用UDP数代填 |
| CSI记录数 | RX实际导出的CSI记录，另报目标MAC/有效/解析失败/导出丢失；core/stream拆分另说明 |
| 可唯一关联数 | 有完整证据链唯一关联的业务packet_id；近似匹配不能并入精确数 |

原帧采集也可能漏帧，报告其来源和计数口径；不把观察数声称为全空中真实帧总量。发送业务数、无线帧数和CSI数可以不同，不能据业务数为分母给“无线CSI丢包率”。CSI覆盖率只在分母和观察边界可用时报告；验收不要求100%覆盖。

## 8. 验收与故障顺序

| 项目 | 通过条件/必须报告 |
|---|---|
| 版本准备 | Pi型号/无线芯片、OS/内核、nexmon/nexmon_csi、nexutil模式、firmware hash均记录；有线管理和恢复可用 |
| CSI基线 | 有CSI、正确来源MAC、合法长度/chanspec、幅度合理、持续采集；停止测试发送有对照；不要求跨包绝对相位连续 |
| 5分钟稳定性 | 实际有效CSI频率、捕获丢失、错误长度/间断、系统负载/温度记录；不预先承诺性能 |
| Jetson上行来源 | 区分Jetson TX与AP转发，下行不能冒充上行 |
| 业务关联 | 分列发送业务/原Wi-Fi帧/CSI/唯一关联四数，另报歧义、缺失和依据；阈值事先约定，不要求每个无线帧都有CSI |

0 CSI故障树：有线管理仍可达 → nexutil -m/-k读回monitor/信道 → firmware是否正确加载、nexutil vendor模式/driver匹配 → wlan0是否up → 检查NetworkManager/wpa_supplicant/dhcpcd是否争用/改信道 → TX流量、过滤和wlan0/UDP5500抓取 → parser版本。

[#398](https://github.com/seemoo-lab/nexmon_csi/issues/398)是Pi3B+/旧系统用户在停止dhcpcd/wpa_supplicant后恢复采集的报告；维护者在该Issue指向#395。它支持“管理冲突需排查”的故障分支，不证明新Pi4B默认需要这些操作。只按本次系统状态调整测试Pi相应接口管理并记录恢复，不默认卸载wpa_supplicant、不停止所有服务；#395的unmanage与额外服务停止不是同一件事。

禁止走旧失败方向：拿USB Wi-Fi替代板载芯片；把空PCIe查询当没Wi-Fi；假定最新OS兼容；混用新旧driver/Makefile；直接卸载wpa_supplicant解决问题；重配Jetson eth0/Mihomo；用AP下行CSI声称Jetson上行。

## 9. 记录与交付

建议本阶段下`树莓派4B测试/结果/<run_id>/`保存manifest、构建/运行日志、固件与驱动信息、CSI PCAP、原帧记录（若能获取）、业务发送/接收日志、匹配表、幅度图和结论。测试前后保存有线管理/无线恢复状态。

```text
Pi型号/芯片/OS/架构/内核：待填
nexmon/nexmon_csi/nexutil/firmware hash：待填
旧driver路线或Makefile.rpi路线：待填
信道/带宽/core/stream/目标TX MAC：待填
已从Pi实机验证：待填
配置/代码推断：待填
尚未验证：待填
CSI基线/普通TX来源/精确或近似关联：待填
发送业务数 / 原始Wi-Fi frame数（不可观察写未测） / CSI记录数 / 可唯一关联数：待填
有效率、歧义/缺失、捕获/导出丢失与系统负载：待填
相位边界：不把跨包绝对phase continuity作为基线条件
恢复状态和下一步：待填
```

官方入口：[Nexmon主项目](https://github.com/seemoo-lab/nexmon)、[CSI仓库](https://github.com/seemoo-lab/nexmon_csi)、[新内核教程#395](https://github.com/seemoo-lab/nexmon_csi/discussions/395)。文档核验不等于本项目已完成Pi实机复现。

## 本轮核验的证据分级

- **官方仓库事实：** 支持表/数据结构、当前Makefile.rpi中的工具与固件操作入口；不等于我们的硬件结果。
- **维护者说明：** #395对Pi4B/Trixie及monitor状态的说明、#391的跨包相位限制；作为主线/验收边界依据。
- **社区Issue经验：** #398原作者的旧环境服务冲突排查；#390 zeroby0的采集空窗解释，未独立复现，不误称维护者确认。
- **仍需本项目实测：** 到货image/kernel/firmware组合、有效CSI来源/长度/稳定率、实际漏样本情况、原帧可观测性、Jetson及业务关联。

本轮未执行任何部署/抓包/硬件测试；共同实验层级、Jetson保护边界与80MHz高可信推断保持不变。
