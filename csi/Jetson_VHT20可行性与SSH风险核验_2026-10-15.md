# Jetson VHT20可行性与SSH影响核验

日期：2026-10-15；服务于明天2026-10-16实验。**仅离线分析，未修改Jetson配置，也未做20MHz实机切换。** 本次SSH超时，用户确认Jetson未开机；不把超时解释成驱动或网络故障。板上最后确认是sniffer-5-packet-id且已STOP，本轮未操作ESP。

## 1. 当前进度恢复

最新100个48字节UDP探针已由Windows完整收到100/100；C5采到63条目标Data FRAME与63条有效CSI，元数据63/63配对，全部Protected1、可见packet_id0，因此业务ID关联未建立。此前物理实验动态响应有支持，但RunA碰线移动导致静止基线无效，静态遮挡重复性不足。来源/元数据配对不能写成全空口帧覆盖或UDP逐包关联。

当前下一阶段计划是先验证Jetson上行VHT20，再评估raw受保护帧/EAPOL和离线业务ID恢复。本轮仅核验VHT20能力及SSH风险，不执行P1写参数、AP改宽、重连、驱动重载或后续解密。

## 2. 结论分级

|问题|判断|证据级别|
|---|---|---|
|RTL8821CU能否以20MHz并保留VHT发送|有高可信的能力与驱动源码依据，值得现场验证；不等于已完成实机VHT20测试|旧实机能力记录+源码推断|
|能否只限Jetson上行，不动AP|匹配版本字符串的公开源码有运行时tx_bw_mode接口，专门限制发送带宽，是优先候选|源码确认；本机接口存在性/编译版本待确认|
|是否一定要重载驱动/重连|不一定；该运行时setter只更新发送限制并安排速率控制更新，没有显式断开/重关联调用|源码路径推断，非实机零中断保证|
|SSH能否保证不断|不能保证。运行时TX限制预期风险较小；重关联/模块重载则会使wlan0阶段性不可用|工程风险评估，待现场|
|会不会改IP/SSH配置/eth0|纯TX限制的目标不涉及这些配置；但若重连DHCP/NM重配置，地址或路由可能变化，现有网络流量也可能受影响|有条件推断|
|20MHz是否强制每帧VHT|不是。速率控制仍可能使用legacy/HT；必须实测VHT Data及有效VHT CSI|协议/驱动行为限制|
|改20MHz是否解决Protected|不会。带宽与WPA载荷保护是两个问题|当前任务边界|

## 3. 与旧实机版本匹配的源码依据

旧2026-10-13只读报告：USB驱动名rtl8821cu，内核模块名**8821cu**，版本**v5.4.1_28754.20180921_COEX20180712-3232**；不是默认假定的模块rtl8821cu。旧proc状态bw_mode0x21、vht_en1。

在线核验候选仓库brektrou/rtl8821CU，固定参考commit：`8c2226a74ae718439d56248bd2e44ccf717086d5`。

- [include/rtw_version.h](https://github.com/brektrou/rtl8821CU/blob/8c2226a74ae718439d56248bd2e44ccf717086d5/include/rtw_version.h)：版本字符串与旧实机记录相同。**同字符串不能证明当前Jetson加载二进制等于这个commit**，载板厂可能打过补丁。
- [os_dep/linux/os_intfs.c](https://github.com/brektrou/rtl8821CU/blob/8c2226a74ae718439d56248bd2e44ccf717086d5/os_dep/linux/os_intfs.c)：rtw_bw_mode用于支持带宽、rtw_tx_bw_mode用于最大发送带宽，两者都不是MHz整数；loadparam将module全局值复制进adapter registry。
- [os_dep/linux/rtw_proc.c](https://github.com/brektrou/rtl8821CU/blob/8c2226a74ae718439d56248bd2e44ccf717086d5/os_dep/linux/rtw_proc.c)：proc_get_tx_bw_mode读取driver_tx_bw_mode及分频段宽度，proc_set_tx_bw_mode更新该运行时字段，并在关联时请求RA速率控制更新。注册节点名tx_bw_mode，受CONFIG_PROC_DEBUG等编译条件影响。

### 参数语义不能混用

- rtw_bw_mode：能力/工作带宽上限，影响初始化/能力协商方向。
- rtw_tx_bw_mode：模块初始化默认TX上限；sysfs显示0644只说明可写，不保证改当前适配器立即生效，因为有registry初始化副本。
- proc中的tx_bw_mode：当前adapter发送限制的专用运行时入口，较符合“只控上行”的目标。候选路径`/proc/net/rtl8821cu/wlan0/tx_bw_mode`，真实路径必须现场读取，不能凭源码假设存在。
- rtw_vht_enable：VHT开关，不是带宽。不能通过关闭VHT来冒充VHT20成功。

此参考源码用低4bit表示2.4GHz、上4bit表示5GHz，宽度编码0/1/2分别20/40/80MHz。以旧0x21为例：如果只限制5GHz到20并保持2.4GHz原值，候选编码是0x01，而不是把“20”这个十进制数写进去；proc解析用十六进制格式。这只是**源码语义例子，非本轮执行指令**。现场应根据实际读出的旧值保留低位，恢复时写回实际旧值，不把0x21当所有设备默认。

[drv_types.h](https://github.com/brektrou/rtl8821CU/blob/8c2226a74ae718439d56248bd2e44ccf717086d5/include/drv_types.h)的ADAPTER_TX_BW宏读取driver_tx_bw_mode，而VHT enable独立；初始化另把registry.tx_bw_mode复制到该字段。这补足了module全局→初始化副本→运行时TX字段的区别。参考autoconf默认启用proc debug，但不能据此断定实机编译开启。

候选运行时TX限制不会要求AP BSS跟着缩窄；关联宽度cur_bw/oper_bw可能仍80。这样读数仍宽不能直接判定TX限制失败；反过来仅参数显示20也不能证明逐包空口VHT20。必须结合TX限制读回、实际Data PHY和C5有效VHT CSI证据。

不要把`iw set channel ... HT20`当作managed STA的TX限宽方法；[Linux v5.10 nl80211.c](https://github.com/torvalds/linux/blob/v5.10/net/wireless/nl80211.c)中STA信道由连接过程管理，显式设信道不是这里要修改的TX策略。也不要把关闭VHT或仅降低码率当成VHT20验收。

## 4. 对SSH与其他链路的具体影响

|路径|对wlan0/SSH的预期|明天定位|
|---|---|---|
|只读cat/modinfo/iw link|不改变无线状态，SSH正常只读使用|开场第一步|
|已确认存在且匹配语义的运行时tx_bw_mode|没有主动重关联步骤，预期可在原AP/原IP上继续SSH；仍可能短时丢包或驱动兼容问题，不保证已有SSH一直存活|首先评估；首次写入也要现场回退|
|只写/sys/module参数|可能只改全局变量却不改变adapter，造成“读回改了、实际没改”的误判|不作为已生效依据|
|重关联/接口down-up/重载模块|wlan0暂时断开；原SSH可能卡住、掉线，通常要重新登录，重连失败可能需本地恢复|不通过唯一wlan0 SSH盲做|
|改AP的5GHz BSS宽度|可能影响所有5GHz客户端，包括Windows与Jetson，管理入口也可能短时失联|仅经现场/设备授权后的fallback|

纯TX限宽不会主动改ssh服务、端口、密钥或登录密码；主要风险在承载SSH的无线链路。若仍关联同AP且IP保持，新的SSH应可继续使用原地址；若发生DHCP更新/漫游/接口重建，原地址不保证，需现场查看当前IPv4再连接。短中断时TCP SSH有时能恢复，不能把“有时”当保证。

同一USB Wi-Fi模块的流量都受TX上限影响，吞吐可能下降，不只UDP探针；目前5pps/48byte探针和交互SSH负载很低，但实际吞吐/时延不承诺。eth0无需也不应参与限宽操作；Go2/MID360内部接口保持原样，仍不能保证任意wlan依赖程序对断线完全无感。

首次写入前应有显示器/键盘或已经验证的独立USB-RJ45管理；目前eth0是内部网络，不能当空闲口使用。自动回退定时器只能是额外保障，不能代替首次独立管理，也不能在未核验driver语义时盲写。

## 5. 明天2026-10-16执行门禁

1. 开机、固定ESP/线缆，读取当前状态与v5版本；本次不重跑Router基线。
2. 先执行本地准备的[只读检查脚本](Jetson只读工具/vht20_preflight_readonly.sh)对应检查（脚本仅静态验证，未在Jetson执行）：精确module/version、参数与权限、proc tx_bw_mode、AP/信道、IP/SSH路由。不要sudo写入、扫描/切网或重载。
3. 若运行时节点存在，记录原始完整值和5G解码结果，并核对源码路径；若不存在或语义不匹配，标记该候选不可用，不能猜路径/数值。
4. 确认独立管理/本地恢复，然后才另行进入一次临时TX限宽测试；首次不写永久modprobe配置、不重启，不优先改AP。
5. 先验证SSH/关联/地址持续性与TX限制读回，再C5监听目标Data、rx_format是否VHT、VHT有效CSI/长度及FRAME↔CSI配对。20MHz上限只给VHT20可能性，不保证低速探针每包VHT。
6. 若只看到legacy或没有CSI，不能声称VHT20成功，也不能直接认定driver限宽无效；分别检查上行PHY、CSI配置和接收覆盖。无需强迫cur_bw必须变20来满足“只限TX”实验。
7. 一次实验后恢复**实际原值**，检查SSH、wlan0、默认路由与eth0原状态；停止临时流量、释放端口、退出新增SSH。
8. Jetson端无可靠方法时，再评估可授权AP的20MHz BSS fallback；路由器芯片支持20MHz不等于当前小米R4固件UI一定可手动锁定。AP能力/控制菜单仍需实际核验。

## 6. 当前仍未知

Jetson当前是否带proc运行时节点、实际参数值、厂商补丁/加载二进制与参考源码一致性、限TX后是否维持关联、现有SSH是否存活、回退后是否完全恢复、目标Data是否实际VHT20、C5有效VHT CSI、AP当前固件20MHz控制菜单，均未做本轮实机验证。

本轮新建文档和只读工具，未改变Jetson/ESP/AP配置。明天实验计划不等于已授权本轮立即切网；没有创建自动定时任务。
