# ESP32-C5 CSI物理合理性验证结果

本轮已完成五组及5cm补充遮挡/恢复，未重复Router实验，未进入packet_id/传感器/AP Plan B。结论为**部分支持：动态响应与局部恢复有证据，完整可重复静态遮挡验收尚未建立**。没有标准仪器ground truth，不宣称绝对数值校准。

## 1. 实验状态与Run A失效

每组动作均先等待用户确认，设备/AP原则上固定，手掌不触碰天线；先A静止→B约10cm静态遮挡→C静止→D约10–30cm慢速运动→E静止，再补充约5cm静态遮挡和恢复，各60秒独立目录。

全部采集结束后，用户明确补充“最初Run A碰到线导致ESP动了一下”。因此A不是合格静止基线，整组标记invalid，不能事后裁掉未知时段来制造稳定结果。原始数据/图表保留并标注INVALID；物理组间比较和静止稳定性判据排除A，使用C/E及补充恢复。原来的“初始静止原因未知”被此现场说明替代，不推断硬件损坏或CSI错误。

## 2. 来源、SDK与版本

来源结论引用实验2：Jetson MAC与header TA一致，上行QoS Data、ToDS1/FromDS0，以及独立FRAME/CSI同帧元数据。此次重新读取目标MAC/频率/默认网关；七组来源/方向持续一致，无header冲突。仅来源/SDK有效不能替代物理验证。

- QSZNTEC ESP32-C5 rev1.0/4MB/外置天线；ESP-IDF5.5.5，UART COM10/921600。
- 独立sniffer-4-physical基于sniffer-3保留全部回调/目标计数；UART仅输出目标Data FRAME及有效DataCSI，Control/Management只计数。核心NULL/信道149接收和CSI配置未改。
- 构建/分区检查/烧录Hash通过，七组启动均为sniffer-4-physical，ELF前缀435ed7c3d与manifest完整hash一致。当前源码/本次build/flash/启动确认一致；结束发STOP，板保留该固件但CSI/prom停止。
- 先30.157秒sanity：有效上行CSI37、FRAME37、1.227条/s，queue/JSON错误0。
- 正式七组535条CSI全部estimate_valid1、rx_state0、first_word_invalid0、copied=len106、非空非全零；format1/second0/L-SIG rate11一致，未混PHY。12位分量饱和计数0。

## 3. CSI“频率”与记录质量

RF频率5745MHz/信道149；当前NULL模式ESP实际RX带宽未直接测量。当前记录是legacy OFDM，不能把Jetson链路VHT80高可信推断或C5原Router协商BW20当成本次每包带宽测量。

Jetson仅普通用户运行实际读取的wlan0网关ping：interval0.2秒、payload256字节，约5请求/s；整个正式序列同一ping配置。接收合格帧触发CSI，5ping/s不等于5CSI/s，20MHz更不等于CSI采样率。

|组|实际ARMED→STOP秒|有效Data回调/落盘条数|回调条/s|落盘条/s|CSI队列drop|非CSI JSON错误|
|---|---:|---:|---:|---:|---:|---:|
|A 静止（设备被碰动，无效对照）|60.187|67|1.113|1.113|0|1|
|B 10cm静态遮挡|60.313|83|1.376|1.376|0|1|
|C 静止/恢复1|60.297|72|1.194|1.194|0|0|
|D 手掌运动|60.031|79|1.316|1.316|0|0|
|E 静止/恢复2|60.406|74|1.225|1.225|0|0|
|补充5cm遮挡|60.203|73|1.213|1.213|0|0|
|补充5cm恢复|60.172|87|1.446|1.446|0|0|

所有七组Data CSI回调数=落盘数，无CSI解析损失；设备FRAME/CSI队列drop全0，明显改善旧sniffer-3的密集Control导出。A有一行FRAME、B有一行STATS被STOP时wifi:ic_disable_sniffer日志插入而解析失败，FINAL计数完整；这2行保留原始证据，不算空口丢失。此次未中途改固件；后续可串行化STOP日志输出，尚未修复。计数有极短ARMED前开启窗口，host时间含约0–0.5秒读取边界偏差，非硬件同步标定。

## 4. 本轮联网核验与解析规则

[官方C5 v5.5.5 CSI指南](https://docs.espressif.com/projects/esp-idf/en/v5.5.5/esp32c5/api-guides/wifi.html#wi-fi-channel-state-information)、[同版esp_wifi_he_types.h](https://github.com/espressif/esp-idf/blob/v5.5.5/components/esp_wifi/include/esp_wifi_he_types.h)、[native结构](https://github.com/espressif/esp-idf/blob/v5.5.5/components/esp_wifi/include/local/esp_wifi_types_native.h)以及[IDF #18493维护者说明](https://github.com/espressif/esp-idf/issues/18493)已重新在线核查。

当前lltf_bit_mode=0表示12位LLTF，不能直接套用常规指南的8位复数对。按维护者解释，每4字节为1复数槽，real/imag各小端16位读取低12位并符号扩展，幅度hypot(real,imag)；互换I/Q不影响幅度。保留raw106字节，先104字节解26槽，尾2字节保存并分布统计，不赋予未经证实的含义。官方对完整线性子载波顺序未消除歧义，图横轴是packed complex slot，不能称精确物理子载波/DC。

first_word_invalid真时遮罩首4原始字节对应首槽（本轮全0）；槽13全零仅标候选，不声称已经确认DC，不从主统计偷偷删除，另有排除恒零槽敏感性对照。8位可选分析路径未在本板验证，不能用于当前mode0数据。

每包RMS/L2归一化用于区分共同幅度缩放和形状变化，不保证AGC校准；raw和归一化均保留。原始字节高位格式也与12位分组一致，但这不是绝对定标。按共同L-SIG rate11分层；统计为不规则到达包的样本均值/样本方差(ddof1)，未重采样、不是按均匀时间加权的频谱。phase不作跨包绝对连续性验收。

[esp-csi当前仓库](https://github.com/espressif/esp-csi)作为信道环境感知用途依据；[C5社区案例#270](https://github.com/espressif/esp-csi/issues/270)只作输出背景，不承诺社区1000Hz性能。精度布局以本次固定IDF头文件/维护者解释为准。

## 5. 幅度、形状、动态与恢复

下表槽13保持在主统计中，A只作受干扰诊断，单位是SDK数值，没有绝对信道增益校准。

|组|平均RSSI dBm|平均raw幅度|平均槽raw时间方差|平均槽RMS归一化时间方差|
|---|---:|---:|---:|---:|
|A 静止（设备被碰动，无效对照）|-50.21|211.233|2769.415|0.053874|
|B 10cm静态遮挡|-44.39|227.348|28.164|0.000458|
|C 静止/恢复1|-44.76|227.411|35.637|0.000588|
|D 手掌运动|-45.77|226.678|113.727|0.002019|
|E 静止/恢复2|-45.04|225.134|21.019|0.000329|
|补充5cm遮挡|-46.26|227.358|66.141|0.001118|
|补充5cm恢复|-45.59|226.870|47.827|0.000796|

- **运动响应：** D归一化方差是C的3.43倍、E的6.13倍；raw方差也增加。归一化后仍有变化，不能仅用共同接收功率缩放解释。只有一次运动轮次，不能称已充分复现或排除全部环境干扰。
- **运动后恢复：** E方差降回静止量级，C/E均值向量相关系数0.97476、单位L2距离0.05270；去恒零槽敏感性相关系数0.95019，趋势保留。支持局部静止恢复，不证明回到无效A的原状态。
- **10cm静态遮挡：** B/C形状相关0.99718、单位L2距离0.01576（去恒零槽相关0.97876）。A受碰动失效，不能用A/B的差异当遮挡证据；B/C接近，未得到清楚的遮挡条件区分。
- **5cm补充：** 以E为前静止，E/5cm遮挡距离0.04496、E/移手恢复距离0.03612。恢复略接近，但差异不大，不能凭这次顺序实验宣称稳定可重复的静态遮挡识别。

不设“超过20%即正确”阈值。当前应写“观察到动态响应及停止后的波动下降，支持CSI反映环境变化；静态遮挡与多轮重复性仍需更强控制”。结论属于局部物理合理性支持，完整验收尚未通过；不是CSI错误，也不推翻实验2的来源证据。

## 6. 图与可复现输出

- [图1 RSSI时间](figures/01_rssi_vs_time.svg)
- [图2 每包平均幅度/raw与归一化](figures/02_packet_mean_amplitude.svg)
- [图3 固定等间隔6槽时序/逐组](figures/03_six_slot_timeseries.svg)
- [图4 共同rate下平均归一化响应](figures/04_mean_response_by_rate.svg)、[raw均值](figures/04b_raw_mean_response.svg)
- [图5 每槽时间方差/包含无效A诊断](figures/05_slot_time_variance.svg)
- [图6 有效对照组方差](figures/06_valid_controls_variance.svg)

本地同时保留PNG、每组raw日志/records/frames/设备stats/summary与动作metadata；analysis目录有逐槽mean/variance/std、时序CSV、共同rate组间相关/距离、静止前后半稳定性、掩码/尾字节/饱和统计。选取的6槽由有效槽范围等间隔确定，不挑好看的槽。公开副本只放匿名汇总/向量、图和本人脚本，原始数据及带现场信息的时序不上传。

复现离线命令：python analyze_physical.py --root <本地结果目录> --mac <实际目标MAC> --lltf-mode 12 --runs static1,blocked,static2,motion,static3,blocked5cm,recovery5cm --reference static2。脚本读取run_metadata失效标记，A仍画图但不进入物理比较；不能用默认旧图覆盖现场条件。

## 7. 清理、尚未证明与下一步

临时ping已Ctrl-C终止，正式3508发/3508收，新增SSH退出；ESP各组STOP/FINAL、CSI/prom关闭，COM10复开关闭验证空闲。Jetson Wi-Fi/eth0/IP/路由/DNS、SSH/ROS/Mihomo及服务未改，未安装软件，未操作Go2/相机/雷达。

未证明完整VHT80、所有PHY帧覆盖、精确C5 LLTF槽到子载波/DC/尾字节映射、标准仪器ground truth、packet_id/sample_id、图像/雷达业务、机器人移动或t/(x,y)/sample_id/CSI完整链路。

**下一步建议先固定线缆和ESP位置，做多轮短静止—遮挡—恢复与运动复测，完成稳定基线与可重复性验收，再进入可控packet_id关联。** 本轮不继续执行下一阶段。无需切Jetson到ESP AP，不重跑Router baseline。
