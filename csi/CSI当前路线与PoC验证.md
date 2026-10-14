# CSI 当前路线与 PoC 验证

更新时间：2026-10-14。当前有效路线入口；优先于第二阶段历史文档[CSI调研与实操计划](../simulation/CSI调研与实操计划.md)中以 Atheros 为主的旧安排。

## 目标与当前决定

关联业务样本、上行无线帧 CSI、时间和位置。尽量复用 Jetson RTL8821CU 作为普通 Wi-Fi 发送端，由固定接收端提取 CSI。

当前用户明确后续测试ESP32和Pi4B；现有1块QSZNTEC板照片明确ESP32-C5标识，revision v1.0/Flash4MB已实查，SKU仍未知。ESP顺序为单板路由器基线→保持Jetson网络的探索监听→ESP AP备选（先PC，未来才Jetson）；AX210/PicoScenes保留按需升级。执行入口：[ESP32测试](ESP32_CSI测试方案.md)、[Pi4B测试](树莓派4B_Nexmon_CSI测试方案.md)。

Atheros CSI Tool 已降级为历史参考/备用；旧调研和失败经验保留，不作为主采购或主实现入口。这是路线选择变化，不代表已通过实验否定 Atheros。

已更新文档、核验官方资料并完成授权Jetson只读补查。Windows ESP-IDF5.5.5已安装/激活，ESP板已有实物照片；C5 router构建/烧录/300秒CSI基线已完成；Pi未复现，未修改Jetson网络、驱动、ROS、Mihomo或服务。

## 已确认实机事实与边界

以下为此前现场摸底基础；相机/状态字段、MID360结果见[只读报告](Jetson只读补查_2026-10-13.md)，最新接口与Mihomo路由快照见[接口报告](Jetson网络与扩展接口只读确认_2026-10-13.md)，以最新证据优先：

- Jetson Orin NX，Ubuntu20.04.5、Linux5.10.104-tegra、ARM64；实际JetPack和内存规格仍待核实。
- eth0=<JETSON_ETH0_IP>，承担Go2/MID360内部网络，保持现状；.161是控制侧候选，.20是MID360配置地址，设备身份/线缆终点和实时雷达接收仍待确认。
- SDK2 DDS状态桥使用eth0；已有单帧SportModeState样本，不能证明持续稳定。position[3]只是候选位置，单位、坐标系、原点/重置和stamp时钟基准待确认。
- wlan0为RTL8821CU USB Wi-Fi，支持2.4/5GHz、HT20/40、VHT；用于普通Wi-Fi及SSH。此前关联5745MHz不代表本轮仍是该信道。
- D435i通过USB3.x连接，pyrealsense2相机服务曾返回RGB/Depth；底层有frame timestamp/frame number，但当前HTTP输出未确认保留它们。不能直接开启第二个采集pipeline争抢相机。
- Mihomo曾影响广播路由；无抓包证明业务广播到达笔记本。当前设备运行版本未确认与工作区源码一致。

## 三条路线与采购核对

| 顺序 | 候选 | 官方核验与采购要点 | 必须通过的PoC |
|---|---|---|---|
| 1 | QSZNTEC ESP32-C5，当前1块 | 照片标识明确；电子查询已确认v1.0/4MB，首选UART口。IDF5.5.5已安装，固定源码后纯build；C5支持20/40MHz，不支持80MHz | 路由器基线→探索监听（Jetson80MHz为限制）→ESP AP备选；来源有效性先于业务关联 |
| 2 | Pi4B + Nexmon CSI | 项目列出bcm43455c0/firmware 7_45_189，a/g/n/ac、最高80MHz；核对实际芯片和可复现OS/kernel/firmware组合；配SD卡、电源及有线管理 | 固定信道监听Jetson源MAC，CSI与原帧sequence对齐，另建payload/sample_id关联 |
| 3 | x86-64真机 + PCIe/M.2 AX210 + PicoScenes | 官方支持AX200/201、AX210/211；最高160MHz，associated-AP和monitor-mode CSI；Ubuntu22.04、≥4GB RAM、CPU≥SSE4.2（推荐AVX2）、关闭Secure Boot、真实PCIe/M.2接入，不支持虚拟机或ARM | 原生Linux识别AX210并提取Jetson上行CSI；验证payload关联及实际TX模式 |

ESP AP/CSI接收端是拟议拓扑，不是已跑通的官方交钥匙业务例程。先按所选官方示例跑通，再评估AP模式和UDP收包扩展。

接收端的最高能力不等于链路实际能力：保留RTL8821CU时不能凭AX210规格宣称已获得ax/6GHz/160MHz，也不能保证2×2有效CSI；结果取决于TX、RX和实际协商模式。

## 必须先解决的拓扑与关联问题

1. **管理路径**：Jetson wlan0正在承担SSH。切换到C5 AP可能断开当前管理/互联网连接；先设计并验证独立管理路径或回退方式，不把eth0当空闲口、不预设可同时连接两个AP。本轮不切网。
2. **测量方向**：需确认CSI对应Jetson→接收端的上行帧；若AP转发，不能把AP→节点的下行CSI误标为Jetson上行CSI。
3. **业务与无线帧**：一个UDP样本可能对应多个无线帧，存在聚合、分片和重传；MAC sequence不是sample_id。CSI回调/记录未必含业务payload。需核验所选C5 API/示例字段，再设计原帧与UDP记录联合匹配；只有时间邻近匹配时必须标为近似关联。
4. **Nexmon字段**：官方CSI输出含源MAC和触发帧sequence；这些不是业务payload或全局唯一编号。加上采集轮次、信道、时间、重传/聚合信息，验证回绕与歧义。
5. **时钟**：区分相机采集时间、Jetson发送时间、接收节点CSI时间和落盘时间。不同设备时钟未同步时不能直接相减；记录时钟域、偏移和误差。
6. **业务大小**：先用小UDP标识包验证，之后才扩展压缩图像/特征或雷达数据；全量图像/点云吞吐与CSI日志导出可能成为瓶颈。

## SSH还需要获取什么

结论：授权只读补查已完成并退出；当前无必需SSH任务，先完成单板C5路由器基线。以下保留未来只读核查方法，不构成本轮再次SSH或追查80MHz的要求。SSH不能替代接收端实验与现场辨认。

| 优先级 | 信息缺口 | 建议只读来源 | 用途/限制 |
|---|---|---|---|
| 接入Jetson前 | 当前wlan0频率/信道/带宽、模式、国家码、节能设置 | iw dev wlan0 info/link；iw reg get；iw dev wlan0 get power_save | 规划共同信道/带宽；不执行set、scan或切换连接 |
| 接入Jetson前 | 当前地址、策略路由和测试目的地出口 | ip -br addr；ip rule show；ip route show table all；ip route get 接收端实际IP | 检查Mihomo影响；不要导出代理订阅、密码或完整凭据配置 |
| 接入Jetson前 | SSH管理路径及现有连接依赖 | printf '%s\n' "$SSH_CONNECTION"；ss -tn；NetworkManager设备状态 | 评估换AP中断及回退；只读检查不保证未来拓扑可用 |
| 真实样本阶段 | 相机服务运行解释器/启动方式、时间戳保存逻辑及/status已有字段 | systemctl show/cat 已识别的相机服务；阅读实际服务源码；已有/status接口 | 不重启服务、不启动第二相机pipeline；保留frame number、timestamp及domain计划 |
| 真实样本阶段 | 状态桥实际环境、SDK路径、position/stamp来源 | 现有服务启动配置、源码和已有状态输出 | 不安装cyclonedds；不重跑此前失败的系统Python订阅；坐标定义仍需文档/学长确认 |
| 雷达阶段 | Livox进程、UDP56301/56401监听及已有驱动日志 | ps；ss -lunp；已识别服务日志 | 没有socket不能单独证明设备没发包；不启动驱动 |
| 时间关联阶段 | 当前系统时钟同步状态 | timedatectl status；现有chrony/timesyncd状态 | 仅证明主机状态，不证明传感器/ESP时钟同步 |

确认具体服务名后再读对应配置，避免大范围输出进程环境中的秘密。默认不启用抓包或主动流量测试；确需下一阶段验证时明确接口、目标和时间窗口。

2026-10-13已通过新增SSH会话执行一次授权只读补查；本节保留核查方法，实际结果见[Jetson只读补查报告](Jetson只读补查_2026-10-13.md)。原SSH连接未操作，新会话已退出。

## PoC顺序与验收记录

- ESP当前单板：固定版本、频段、信道/带宽和串口配置，先官方csi_recv_router；保存基线后才独立sniffer实验。未采集前不报告采样率。
- Jetson替换TX：先完成管理路径设计；小包携带run_id/sample_id/packet_id和发送时刻。以1/10/50包每秒作为拟议起点，每档5分钟，再按观测提高；这些是计划参数，尚未验证。
- 每档分别统计发送数、UDP接受数、CSI数、可唯一匹配数、歧义/缺失、重传、日志丢失和有效吞吐；不能把CSI数当UDP样本数。验收门槛按业务目标事先确定。
- 单传感器：先引入D435i少量压缩样本/特征，并记录采集时间、帧编号、业务发送时刻；位姿保留原始stamp和坐标说明。
- Pi4B：先匹配patch版本和原帧/CSI，再复用业务契约；不足时升级AX210。真实MID360整合排在接口和带宽确认之后。

## 官方资料（2026-10-13读取）

- [Espressif esp-csi](https://github.com/espressif/esp-csi)
- [ESP32-C5-DevKitC-1官方指南](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32c5/esp32-c5-devkitc-1/user_guide.html)
- [Nexmon CSI支持与数据格式](https://github.com/seemoo-lab/nexmon_csi)
- [PicoScenes部署条件](https://ps.zpj.io/manual/installation.html)
- [PicoScenes硬件支持](https://ps.zpj.io/manual/hardware.html)
- [PicoScenes测量场景](https://ps.zpj.io/manual/scenarios.html)
- [PicoScenes GitHub组织](https://github.com/wifisensing)

网页核验只证明项目公开支持声明及字段格式；本项目未复现。官方能力不应写成机器狗端到端验证成功。
## 路线C部署与用途边界（2026-10-13修正）

FeitCSI已退出当前主方案，不再采购/部署；此前选择仅保留在执行历史。PicoScenes不得部署在Jetson ARM64、树莓派ARM或WSL中。

主机可选N100/N150等x86小主机、台式机+PCIe→M.2 Key E、内置AX210笔记本；mini PC不是要求。用户现有Win11/AX210笔记本外置SSD原生Ubuntu22.04仅为理论候选，未操作；长期倾向独立x86 Linux主机，由Windows SSH管理。

官方额外要求安装/有效期检查联网，安装/升级会更新内核，必须在专用主机准备阶段明确。关联AP测量的是AP发来的帧，不能直接当Jetson→RX上行；本任务优先评估monitor-mode听到Jetson上行的拓扑。

实测RTL8821CU能力为1条空间流、无160/80+80、无HE/6GHz能力枚举。PicoScenes的AX210最高规格不能视为保留现有TX后的实际链路规格。

2026-10-14补充：Pi4B除旧内核修改brcmfmac方案外，官方现有Makefile.rpi/vendor-command路线可用于较新内核，实际版本仍待核验。ESP当前照片已明确C5标识，仍不能把5GHz支持扩展为80MHz监听；具体芯片/Flash与CSI运行待测。两份测试方案优先于历史采购建议。
