# ESP32-C5 单板 CSI 测试方案

更新：2026-10-14。当前只有1块板；照片明确标注QSZNTEC、ESP32-C5、2.4/5G，外置天线已连接。路由器阶段已按下述记录完成实机验证；监听/AP阶段仍为待执行计划。沿用本文件作为唯一ESP测试入口，不另建重复的“ESP32_CSI测试计划.md”。

## 执行前版本门禁

| 字段 | 当前事实 / 执行前补填 |
|---|---|
| 开发板、数量 | 照片标识QSZNTEC ESP32-C5，1块；具体SKU/电路版本待查，不能认定ESPC5-32E-N4 |
| 芯片/revision、Flash | 板上C5标识明确；已实查C5 revision v1.0、Flash4MB；manufacturer46/device4016 |
| ESP-IDF target | 按标识准备esp32c5；esptool查询若不符先停止并重新核对 |
| 主机、ESP-IDF | Windows；5.5.5已安装/激活，专用Python3.11.2、esptool4.12.0；该固定router例程构建/烧录/本板基线已通过 |
| esp-csi、组件 | 已下载源码8633d67152db2808f141cc1595970aa9cf406045；已解压构建；cmake_utilities0.5.3、esp_csi_gain_ctrl0.1.5及锁文件已保存 |
| firmware | 原板Flash已备份；新构建hash/配置/无app源码diff/烧录日志及运行证据已保存 |
| 频段/信道/带宽/PHY | 本次用现有<TEST_AP_SSID>：5GHz149，C5协商BW20；2.4GHz/20MHz仍未测 |
| 管理/输出 | Windows通过板上UART口；已识别CH343/COM10、UART0/921600，串口采集完成并释放；Jetson仍原wlan0管理 |
| 纯build | 已通过并完成Flash Hash校验；后续新固件仍遵守先build后flash |

顺序：**照片/芯片查询 → target → 固定IDF和esp-csi/组件 → 配置核对 → 纯build → 成功后flash → 原始串口记录 → CSI验收**。已安装5.5.5是本板测试候选，不是已验证CSI组合；不安装latest替换它。

[Issue #267](https://github.com/espressif/esp-csi/issues/267)报告IDF6.0.1下HT20/HT40枚举变化造成编译失败。5.5.5本地头文件仍有这两个枚举，但这只能排除该项静态风险。若编译失败保留日志，先核对target/API/依赖，不默认更新IDF。[#270](https://github.com/espressif/esp-csi/issues/270)的C5+IDF5.5.3+5GHz HE20是社区修改固件案例，约1000Hz不是本项目保证。

## 1. 硬件确认与USB连接

### 照片能确认什么

- 背面印有ESP32-C5、2.4/5G、QSZNTEC；芯片系列已可用于选择target，不再把本板写成“型号完全未知”。
- 模组射频座连接外置贴片天线；照片不能证明该天线的实测双频性能、增益或具体型号。
- 两个Type-C插口标为USB与UART。具体桥芯片是否CH343、板卡是否N4、Flash是否4MB，仍需硬件ID/电子查询或板厂原理图；不凭外观认定。

### 首轮接标着UART的口

| 观察方向（天线/模组朝上，接口朝下） | UART口位置 |
|---|---|
| 用户第一张正面照片，可见金属模组与BOOT/RESET | 左边Type-C |
| 用户第二张背面照片，可见QSZNTEC大字 | 右边Type-C |

**以UART丝印为准。** 用一根能传数据的USB线，电脑USB口→板上UART Type-C；首轮只接这一个口，USB口留空，无需接Jetson或排针。外置天线保持连接，固定朝向/距离，避免贴在金属与散热器旁；>1m是官方实验一致性建议，不是没有外置天线就不能测试的门槛。

UART标识表明它预期通过USB-UART桥访问芯片；桥芯片和具体接线尚未通过原理图/COM验证。推荐此口是因为下载快照的路由器例程明确配置UART0控制台，更便于同时烧录与导出CSI。

另一个USB口预期用于C5原生USB Serial/JTAG。C5官方支持原生USB下载，但本第三方板的接线仍需验证；改插这个口并不会自动把UART日志重定向到USB。首轮不需要同时接两口，也不把它当第二个Wi-Fi接口。[官方串口/USB说明](https://docs.espressif.com/projects/esp-idf/en/v5.5.5/esp32c5/get-started/establish-serial-connection.html)。

### Windows识别（后续现场步骤，本轮未执行）

1. 打开设备管理器→“端口(COM和LPT)”；接UART后记录新出现的COM及设备名称/硬件ID。电源灯亮只能证明有供电，不能证明数据线/驱动正常。
2. 没有COM时：确认是数据线、UART口、电脑直连；查看“其他设备”的硬件ID后才选桥芯片官方驱动。不能未识别就同时安装CH340/CH343/CP210x等全部驱动。
3. 打开已安装的“ESP-IDF 5.5 CMD”。以下COM7是示例，必须替换成实际端口：

```powershell
idf.py --version
python -m serial.tools.list_ports -v
python -m esptool --port COM7 chip_id
python -m esptool --port COM7 flash_id
```

当前esptool4.12.0使用下划线chip_id/flash_id。这两条查询不写Flash，但会尝试复位/进入下载模式，属于对测试ESP的操作，不是完全被动读取。记录识别芯片、revision、Flash ID/容量、MAC与端口；不把MAC叫作业务sample_id。

若停在Connecting：先关闭占用同一COM的monitor/串口软件；仍失败才尝试按住BOOT→短按并松开RESET→松开BOOT，再重新查询。自动下载是否可用由本板电路决定，不短接未知排针。首次原生USB下载的手动进入下载模式也见官方串口文档。

## 2. 环境准备与带宽边界

- 已安装：D:\Espressif\frameworks\esp-idf-v5.5.5；专用Python为D:\Espressif\python_env\idf5.5_py3.11_env。不需要先装Arduino或Espressif-IDE才能跑本例程。
- 已下载：下载/ESP实验准备/中的固定esp-csi ZIP及requirements。源码已解压；已用IDF专用Python/pyserial取得原文并离线统计，GUI独立依赖未安装，可后置。
- 源码/结果实际保存于本第三阶段目录；构建通过英文无空格路径进行（后续可安排映射），不在IDF框架根目录build，不往旧2-模拟仿真写文件。
- 原板固件用途未知；正式flash前确认是否需要保留并备份。查询、构建、烧录、运行是不同验证级别，分别记录。

[ESP-IDF5.5.5 C5 Wi-Fi文档](https://docs.espressif.com/projects/esp-idf/en/v5.5.5/esp32c5/api-guides/wifi.html)明确C5支持20/40MHz，HE为HE20；5GHz HT40可用，但不能当作80MHz接收器。官方也建议开启promiscuous接收更多CSI，证明“C5 sniffer+CSI”有API依据，不保证任意第三方宽带帧都能产生有效CSI。

Jetson此前wlan0为RTL8821CU、<TEST_AP_SSID>、149/5745MHz，80MHz固定为高可信推断；不再追查。C5与其潜在VHT80不匹配是阶段2的重要限制。80MHz网络中仍可能出现20MHz管理/控制/其他帧；看见背景包不能证明已得到Jetson目标数据帧CSI。

## 3. 阶段1：单板+路由器官方Baseline

### 目标与拓扑

```text
测试路由器/AP → ESP32-C5 STA → UART/USB线 → Windows
       ↑              |
       └── Ping请求 ──┘
```

用[官方csi_recv_router](https://github.com/espressif/esp-csi/tree/8633d67152db2808f141cc1595970aa9cf406045/examples/get-started/csi_recv_router)验证本板可以稳定输出AP→ESP的CSI。只有1块ESP也够，不需要第二块TX。本阶段与Jetson无关。

### 操作顺序

1. 首选现成的独立2.4GHz/20MHz测试AP；记录SSID/BSSID/信道/安全模式。不要为此修改机器狗使用的AP；若没有可控HT20测试AP，记录实际参数后先做可用基线，不假装已固定20MHz。
2. 解压固定源码，在英文工作路径进入examples/get-started/csi_recv_router；只对该例程设置target。
3. menuconfig→Example Connection Configuration中配置Wi-Fi SSID和密码；不把密码写入公开日志/截图。确认Component config中的CSI enable和UART控制台配置实际生效。
4. 先纯build。核对生成sdkconfig、依赖锁文件、target、Flash配置和控制台波特率；旧ESP32前缀默认项不一定都对C5生效，不能只看sdkconfig.defaults。
5. 构建通过且原固件保留事项处理后，再烧录到确认的COM；开启monitor，保存原始启动日志及CSV。

```powershell
# 先进入上述例程目录；以下为后续步骤，本轮不自动执行
idf.py set-target esp32c5
idf.py menuconfig
idf.py build
# 只有build成功且端口、target、固件与配置核对完成后：
idf.py -p COM7 flash monitor
```

`flash`会写入固件。`COM7`仅示例；不要在其他例程目录直接复制烧录。默认烧录速度与应用串口输出速度是两个参数。此快照sdkconfig.defaults指定UART0/921600；实际以生成sdkconfig为准，monitor应匹配应用波特率，不能一律115200。启动ROM日志与应用日志也可能速度不同。

### 源码已确认的边界

[实际app_main.c](https://github.com/espressif/esp-csi/blob/8633d67152db2808f141cc1595970aa9cf406045/examples/get-started/csi_recv_router/main/app_main.c)：连接AP后获取BSSID，CSI回调过滤该BSSID，并启动Ping。CSV的seq来自本地s_count，不是Ping序号、802.11 sequence或未来sample_id。

C5配置开启legacy/HT20/HT40采集，但acquire_csi_vht/su/mu等为false；因此第二轮5GHz也先验证受支持的legacy/HT20/40，不把原版例程描述成已启用HE/VHT所有格式。CSV len/数组还可能经过格式换算与增益补偿，不能把打印列直接当SDK原始buffer字节数。

### 成功标准与失败排查

- 首先60秒连续出现可解析CSI_DATA，再记录5分钟；来源MAC与AP BSSID一致，RSSI/信道合理，无持续复位或明显串口截断。
- 保存表头、实际PHY/带宽、len分布与原始数据；幅度变化可作合理性检查，不作为定位成功证据。
- 成功只证明本板的路由器基线，不证明Jetson上行/业务关联已完成。
- 连不上AP：核对SSID/密码、安全方式、频段、RSSI及连接日志；不要改Jetson。
- 联网但零CSI：检查CSI enable、Ping是否有回复、BSSID过滤、采集PHY开关及实际帧模式。
- 乱码/缺行：查COM占用、UART波特率、主机读取；输出丢失不能直接当无线丢样本。
- 2.4GHz通过后再单独尝试5GHz，保存新run_id；不因5GHz存在就宣称80MHz可采。

依据：官方例程/源码、C5 Wi-Fi Guide。#267为版本风险，#238为长度解析风险，#270为C5社区参考；均不能代替本板运行结果。

## 4. 阶段2：保持Jetson原网络，探索被动监听

### 目标与拓扑

```text
Jetson RTL8821CU → 原小米AP（连接保持现状）
          \
           └→ 同信道ESP32-C5监听 → UART → Windows CSI?
```

仅验证ESP是否能得到发射地址为Jetson的有效CSI。不换Jetson Wi-Fi，不为本实验安装软件、改服务或发送机器人数据。默认观察已有流量；未来若需要主动测试流量，另定目标/速率，只面向测试端。

### 准备与操作（待实现/测试）

1. 路由器基线通过后创建独立sniffer实验版本并保留diff，不覆盖原版。
2. ESP侧选择对应5GHz主信道/合法国家码、promiscuous及CSI回调；具体API、帧过滤和采集PHY设置按5.5.5检查。ESP不能仍固定在2.4GHz信道，也不能在不同AP信道上关联并假设同时监听149。
3. **原版路由器例程的BSSID过滤必须调整**，否则Jetson源CSI会被程序主动丢弃。监听版本应分别统计promiscuous可见帧与CSI记录，不把抓包回调出现等同于CSI有效。
4. 目标为此前Jetson MAC <JETSON_MAC>（现场若变化需重新核对）；同时保留AP/其他来源作为对照，不把AP转发帧误标Jetson。
5. 记录帧类别、可见发射地址、信道、PHY/长度/有效性；CSI与帧回调并不必然一一对应。增强版callback仅快速复制/入队，串口输出交给独立task。

### 判定与失败原因

- 成功：持续取得可核对Jetson发射MAC的有效CSI；能说明所采帧类型/PHY及有效性依据。它反映的是**Jetson→ESP**信道，不是Jetson→小米AP原接收端信道。
- 只看到AP CSI：只能记录AP→ESP结果，不算Jetson上行成功。
- 能看到目标帧但没有有效CSI：保留两类计数，排查带宽/PHY、CSI开关、过滤、聚合/加密/beamforming等候选因素；不可未经证据断言具体根因。
- 没有看到目标帧：先核对信道/目标MAC、现有上行流量和接收模式；不能凭此证明CSI API不可用。
- 当前VHT80与C5能力不匹配：本阶段定义为探索性测试。失败不能否定C5对所有第三方STA的CSI能力。需要用独立测试网络中的普通PC/STA、受控20MHz发射作为对照，再区分宽带限制与实现错误；不修改机器狗网络来做这个对照。

依据：[官方C5 sniffer/CSI说明](https://docs.espressif.com/projects/esp-idf/en/v5.5.5/esp32c5/api-guides/wifi.html)、[#124](https://github.com/espressif/esp-csi/issues/124)中协作者说明sniffer能取得其他设备CSI且测量TX→本接收端；其原问题是S3，不能当C5全模式保证。[#229](https://github.com/espressif/esp-csi/issues/229)是C6监听商用Wi-Fi6失败案例及贡献者排查建议，不能写成C5已失败/已成功结论。

## 5. 阶段3：ESP AP+普通STA（Plan B）

### 目标与拓扑

```text
普通PC / 后续Jetson STA → ESP32-C5 AP → CSI → UART → Windows
```

ESP是实际无线接收端，首轮20MHz；STA按双方能力协商，不沿用原小米VHT80。能否稳定运行AP+CSI仍需本板实测，不是现成官方完整业务方案。

### 先PC验证，再考虑Jetson

1. 建立独立AP/CSI固件，记录SSID、频段、信道、带宽、PHY采集设置、固件diff和地址；先由普通PC连接，验证来源MAC正确的有效CSI。
2. 首轮可用PC对ESP的IP执行低频Ping；前提是AP/网络栈可回复。不要假设ESP天然运行iperf3 server，也不为测试默认在Jetson装iperf3。
3. 后续UDP需实际实现ESP接收端，再从小包低速单播开始。payload/sample_id精确对应是下一层任务，当前先验证CSI来源与稳定输出。
4. Jetson接入为未来操作，当前不执行：第一次需现场显示器+键盘，或已经独立验证的管理通道；准备原SSID与恢复方式，不经现有wlan0 SSH远程切换Wi-Fi，不动eth0/Mihomo/Go2/MID360。
5. 实验后按既定恢复步骤回原Wi-Fi，确认Windows SSH恢复；恢复过程也记录实际状态。此处是后续设计，并非本轮授权切网。

成功标准：普通STA→ESP收到有效CSI，MAC可核对，串口记录稳定；随后才单独复验Jetson。失败排查：AP/STA关联→IP/基础收包→受支持帧模式→CSI开关/过滤→有效性→输出瓶颈，不把AP关联成功当CSI通过。

依据：C5官方AP及带宽协商说明、esp-csi API。AP+第三方STA的具体组合与程序尚未验证，不能用ESP-NOW csi_recv的固定payload偏移直接解析普通IP帧。

## 6. 三阶段共同的CSI与记录验收

- 全系列说明只适用于官方明确列出的Wi-Fi芯片ESP32/S2/C3/S3/C5/C6/C61；不扩大到无Wi-Fi的H2/P4宿主。本板已明确C5标识，不再等待第二块ESP来开始基线。
- len按target、PHY、20/40MHz、STBC/LTF、CSI配置建立合法集合，不要求单一值。[#238](https://github.com/espressif/esp-csi/issues/238)的114/228是特定案例；先解析metadata和输出单位，不直接删除不同长度，也不直接盲拆复数。
- 原版baseline先保留现有字段；增强版记录rx_channel_estimate_info_vld（1为有效）、first_word_invalid、rx_state（0为接收成功），并按所选SDK处理无效范围。本地5.5.5头文件已找到这些字段；本次first_word_invalid为0，但valid/rx_state仍未导出；缺字段写unknown，不伪造有效。
- USB串口是默认导出路径，不改为同一测量Wi-Fi高频UDP回传。[#265](https://github.com/espressif/esp-csi/issues/265)是社区收包/时延问题报告，不能当必然缺陷。若实测printf瓶颈再升级为queue/ring buffer→独立task→binary framing，保存版本/CRC/溢出统计。
- 精确关联阶段分别统计发送业务数、原始无线帧数、CSI数、唯一关联数；无线帧不可观测写未测。UDP可能聚合/重传/分片，不能宣称一包=一帧=一条CSI。
- ESP timestamp、Windows落盘时间、Jetson墙钟不是同一时钟域；未同步不直接计算单向延迟。CSV本地序号不替代sample_id。

## 7. 保存结果与今天的停止点

结果放本阶段ESP32测试/结果/<run_id>/，保存manifest、串口原文/表头、sdkconfig、依赖锁/仓库版本、构建/烧录日志、固件hash、解析器schema/diff。不要公开SSID密码。

```text
硬件：QSZNTEC ESP32-C5，1块；具体SKU/revision/Flash待电子查询
串口桥/硬件ID/COM/控制台波特率：待填
ESP-IDF/esp-csi/组件/firmware hash/upstream diff：待填
拓扑/频段/信道/实际带宽/PHY/目标MAC：待填
已从本板运行验证：待填
仅照片/源码/官方文档确认：待填
尚未验证/失败候选因素：待填
CSI len分布/有效无效未知/串口丢失：待填
业务数/原帧数/CSI数/唯一关联数：未到该层则写未测
下一步：待填
```

今天最优先：**接UART → 确认COM/芯片/Flash → 固定组合纯build → 单板路由器基线60秒/5分钟**。完成基线后再准备监听版本，不把所有阶段挤在第一次烧录里；不接真实相机/雷达/位姿大流量。

## 8. 证据分级与尚未知

| 级别 | 当前结论 |
|---|---|
| 实物照片直接确认 | 1块板由用户说明；ESP32-C5/QSZNTEC/2.4/5G丝印、USB/UART双口、已接外置天线 |
| 官方明确能力/源码事实 | C5支持20/40MHz、原生USB/桥接UART、sniffer与CSI API；官方单板路由器例程；该快照BSSID过滤、本地seq与UART配置 |
| 高可信推断 | UART口已通过CH343/COM10实际查询与采集验证；Jetson80MHz维持此前等级，不继续追查 |
| Issue证据 | #124协作者解释；#229贡献者建议与C6用户失败；#238贡献者长度解释；#267/#265/#270为社区特定环境报告 |
| 本项目仍须实机 | 2.4GHz基线、channel-estimate valid/rx_state与各PHY合法len、第三方监听/AP+CSI、性能上限、Jetson与sample_id关联；本次C5v1.0/4MB/COM10/固定router组合已测 |

最新执行：本板查询/备份/构建/烧录/300秒router采集已完成；未SSH或修改Jetson/AP/Windows网络。Pi4B方案保持独立执行，AX210 PicoScenes为升级路线，Atheros仍历史参考/备用。

## 当前已完成的阶段1结果

- 本次直接采用用户当前<TEST_AP_SSID>，未做2.4GHz测试；ESP实际协商5GHz149/BW20，IP<ESP_IP>。
- 300.03秒（含启动联网）采集28861条AP→ESP CSI；首末CSI时间跨度285.141275秒，观察记录率101.213条/秒。全部来源AP BSSID，打印len106与数组对应；解析/长度错误、本地seq中断、全零数组均0。
- 这不证明每条channel estimate物理有效（原版未导出valid）、Jetson监听或业务关联。len106仅本次观察，不能写死验收。
- 结果：[路由器基线报告](ESP32测试/结果/c5_router_20261014/ESP32-C5_路由器CSI基线结果.md)。原Flash已备份，COM10已释放，板上router固件仍运行。
