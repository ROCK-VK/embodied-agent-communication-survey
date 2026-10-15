# 小型UDP packet_id与CSI关联阶段

更新：2026-10-15。此文记录小UDP packet_id↔CSI阶段方案与当前边界。sniffer-5已烧录并通过sanity；Jetson→Windows UDP收发100/100成功、FRAME↔CSI metadata匹配63/63，但Protected=1导致业务packet_id↔CSI尚未建立。

## 当前已知起点

- 物理CSI验证为部分通过：Jetson上行Data CSI来源与SDK有效字段成立；手掌运动时归一化幅度方差比邻近静止高3.43倍/6.13倍，停止后局部回落。Run A因碰线导致ESP移动而无效；10cm/5cm静态遮挡重复性不足。535条有效Data CSI，UART queue drop=0。完整证据见本地`ESP32测试/结果/c5_csi_physical_validation_20261015/`。
- 工作区/build的`sniffer-5-packet-id` bin=0xdb9a0（app分区0x100000，14%余量）；已校验SHA256后通过COM10/esptool4.12.0只写app区0x10000，回读Hash verified，bootloader与分区表未重写。30秒静止sanity收到匹配READY并STOP/FINAL；具体计数见项目当前状态与执行记录。新捕获脚本会拒绝READY版本不匹配的板卡。
- Jetson通过现有Wi-Fi接入，而C5为WIFI_MODE_NULL未关联旁路监听器。30秒sanity中普通Jetson Data CSI的Protected位为34/34；尚未发送探针，探针帧自己的Protected结果待测。若探针Protected位为1，v5不会尝试解密或扫描UDP载荷，因此不能保证能读到`packet_id`。

## 探针数据格式

每个UDP负载固定48字节，5包/秒，默认100包。无ACK、无重试层；接收端用到达日志核实业务数据是否到达。

| 偏移 | 长度 | 含义 |
|---:|---:|---|
| 0 | 4 | ASCII `CSID` |
| 4 | 1 | 版本，当前1 |
| 5 | 1 | 头长28 |
| 6 | 2 | flags，小端，必须为0 |
| 8 | 4 | run_id，小端uint32 |
| 12 | 4 | packet_id，小端uint32 |
| 16 | 8 | Jetson monotonic时间ns，小端uint64 |
| 24 | 2 | 固定测试数据长度16 |
| 26 | 2 | 保留位，必须为0 |
| 28 | 16 | 可复现测试字节：`(packet_id + offset) & 255` |
| 44 | 4 | 对前44字节计算的IEEE CRC32，小端 |

Jetson sender只需Python 3.8标准库。Windows接收端也只用标准库。两端文件都用新路径、拒绝覆盖；输出日志只记ID、计数与本机接收时间，不记录UDP原文或凭据。

## C5识别和配对

- sniffer-5保留v4的CSI原始采集/目标过滤/统计行为，并额外记录Frame Control的Protected位。
- 仅对未加密、非分片IPv4/UDP Data帧，解析LLC/SNAP、IPv4、UDP和48字节探针；校验magic、版本、长度、保留位、测试数据模式及CRC32。只输出`app_run_id`、`app_packet_id`、发送monotonic时间和状态码，不输出业务payload。
- `app_probe_status`：0=未扫描；1=Protected位为1并跳过；2=不是可识别探针；3=魔数命中但格式/CRC无效；4=完整验证通过。
- FRAME和CSI回调分别尝试读取packet_id。若CSI回调未直接取到ID，但FRAME取到ID，则分析器用timestamp、TA、FC和seq_ctrl将ID与CSI合并；另行汇报所有目标FRAME↔CSI元数据键匹配数及一对一/歧义数，不把“Protected后没有ID”误报成“FRAME和CSI没有配对”。多帧/重传/聚合造成的重复仍按观测逐条保留，不假设一包UDP恒对应一个CSI。
- 当前物理层CSI时间戳不是Jetson系统时钟。sender时间只用于标识与后续分析；接收端主机时间与Jetson monotonic时钟不直接相减。

## 实机顺序（设备可用后）

1. 保持ESP/外置天线/线缆固定。确认当前sniffer源码/build hash和板上READY版本一致；构建后只有在设备上线且符合当轮授权时才烧录。先做30秒静止sanity，核实channel149、Jetson TA、有效Data CSI和UART drop。
2. Windows在已选定的局域网接口上启动接收端，显式指定该接口IPv4；使用新日志路径。若Windows防火墙询问，只按系统提示选择合适网络范围；不得关闭防火墙。
3. C5运行`capture_packet_id.py`，输入本轮实查Jetson wlan0 MAC并固定channel149。脚本只接受`sniffer-5-packet-id`，先ARM，再保留FRAME/CSI/Stats原始本地证据。
4. SSH登录Jetson后仅执行普通用户态sender，发到接收Windows的IPv4，默认每200ms一个48字节UDP负载，共100个。不得改Jetson IP/route/DNS/SSID/服务，也不启动狗运动控制。
5. 使用`analyze_packet_id.py`核对发送ID、接收ID、FRAME可见ID、CSI直接ID和FRAME↔CSI元数据匹配数；检查Protected标志和各自drop计数。
6. 如果Protected=1且没有ID，结论应是接收与CSI都存在、但当前安全链路不提供payload可见性，业务ID精确关联未建立。停止在此边界；只有用户明确授权并设计独立测试网络后，才改变关联条件。不要把时间近似或帧长度推断写成精确packet_id。

## 本地命令模板

以下命令需在新结果目录中运行；尖括号参数必须按当时实查值填写，不写入脚本或Git。

Windows接收端（先运行）：

```powershell
py -3 .\udp_probe_receiver.py --bind <WINDOWS_WIFI_IPV4> --port 39001 --count 100 --log .\results\receiver_<RUN>.jsonl
```

Windows串口采集端（另一个终端；先刷入并启动v5后运行）：

```powershell
<ESP_IDF_PYTHON_3_11> .\capture_packet_id.py --port COM10 --channel 149 --target-mac <JETSON_WLAN_MAC> --duration 60 --output .\results\capture_<RUN>
```

Jetson发送端（SSH会话；发送目标为Windows接收IPv4）：

```sh
python3 /tmp/csi_udp_probe/udp_probe_sender.py <WINDOWS_WIFI_IPV4> --port 39001 --count 100 --interval 0.2 --log /tmp/csi_udp_sender_<RUN>.jsonl
```

离线分析：

```powershell
py -3 .\analyze_packet_id.py --sender .\results\sender_<RUN>.jsonl --receiver .\results\receiver_<RUN>.jsonl --capture .\results\capture_<RUN> --output .\results\analysis_<RUN>.json
```

部署到Jetson前只复制`udp_probe_sender.py`与`udp_probe_protocol.py`到临时目录；无需pip、sudo或安装包。当前不执行复制/SSH，因为Jetson关机。

## 2026-10-15实机初测结果

- C5运行已校验SHA256的`sniffer-5-packet-id`；保持NULL旁路、channel 149。最终60.204秒采集获得63条目标Data FRAME及63条有效目标Data CSI；CSI/FRAME队列drop=0，CSI empty/truncated=0，STOP/FINAL正常。两条Wi-Fi驱动文本行被计为UART JSON解析错误。
- Jetson sender报告发送100个48字节UDP探针；Windows receiver使用当前Public配置下已有Python UDP入站允许规则对应的解释器，收到100/100个唯一ID，缺失/重复/无效均0。未新增/修改防火墙规则，也未修改Jetson网络、路由、服务或Wi-Fi安全设置。
- 最终采集的63/63目标Data FRAME/CSI均为Protected=1。metadata分析器报告63个共享timestamp/TA/FC/seq_ctrl键、63个一对一匹配；FRAME可见packet_id=0，CSI直接ID=0，ID元数据join=0。因此“UDP发送→接收”和“目标FRAME↔CSI”均成立，但当前旁路节点无法从受保护帧读取业务packet_id，端到端`packet_id↔CSI`未建立。
- 早期几轮没有形成发送与接收器同时运行的完整窗口：接收器先达到空闲超时退出；另有一次运行解释器路径与已有入站规则不一致。最终使用已有允许规则对应的Python解释器、120秒空闲超时完成100/100接收；因此早期0接收不能用来断言无线网络阻断，也没有改变防火墙策略。
- 原始sender/receiver/UART/CSI记录及每次失败尝试保留在本地`ESP32测试/结果/c5_udp_packet_id_20261015_165900/`；公开版本只保留匿名汇总，不含原始无线/串口记录或现场标识。

## 验证与未完成项

- 已完成：Python语法检查；loopback UDP 20包发送/接收校验（20/20、缺失/重复/无效均0）；C5 sniffer纯构建和分区容量检查。Protected计数即使目标frame header长度不足也单独保留。
- 已完成：ESP v5 app烧录/回读校验、启动READY与30秒sanity。Sanity普通Jetson上行Data CSI为34/34 Protected=1，但该窗口无探针；这只提示现有Wi-Fi上行帧可能加密，不代替探针实测。
- 已完成：Jetson实际发送、Windows实际接收、探针Protected位实测及通用FRAME/CSI元数据配对；未完成：业务packet_id↔CSI精确关联。源码/构建与板上版本已通过本轮烧录/READY核对；未来重刷后仍需重新核对。
- 捕获器在打开COM串口后会沿用已验证采集器的RTS脉冲复位C5，再等READY；首轮漏复位导致错过一次性READY，未开始采样。失败输出保存在本轮结果目录。
- 已知限制：协议仅解析IPv4/UDP与小型未分片探针；受保护帧不会读取payload；无线传输无ACK，CSI数量与UDP包数无需相等。
