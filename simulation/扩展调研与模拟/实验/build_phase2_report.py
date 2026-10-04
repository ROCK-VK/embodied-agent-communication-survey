"""Write narrative and exact tables from current measured artifacts, never invented numbers."""
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]

def main():
    summary=pd.read_csv(ROOT/'结果/图像实验/summary.csv')
    runs=pd.read_csv(ROOT/'结果/图像实验/runs.csv')
    deltas=pd.read_csv(ROOT/'结果/图像实验/paired-differences.csv')
    metadata=json.loads((ROOT/'结果/图像实验/metadata.json').read_text(encoding='utf-8'))
    network=json.loads((ROOT/'结果/网络实验/summary.json').read_text(encoding='utf-8'))
    learning=pd.read_csv(ROOT/'结果/网络实验/receiver-training.csv').set_index('case')
    a2a=json.loads((ROOT/'结果/A2A整合/summary.json').read_text(encoding='utf-8'))
    audit=json.loads((ROOT/'结果/综合审计.json').read_text(encoding='utf-8'))
    env=json.loads((ROOT/'环境/environment-manifest.json').read_text(encoding='utf-8'))
    docs=json.loads((ROOT/'结果/宇树官方资料核验.json').read_text(encoding='utf-8'))
    proxy=json.loads((ROOT/'结果/代理目标精确解.json').read_text(encoding='utf-8'))
    names={'redundant':'重复帧','sensor_shift':'感知失配','annotation_noise':'标注噪声',
        'interval':'固定间隔','random':'随机','confidence':'高置信度','uncertainty':'高不确定性','diverse_cost':'差异/成本候选','all_reference':'全量参考'}
    lines=['# 感知数据选择、通信网络与 A2A 综合模拟报告','',
        '项目：基于多模态机器狗的通感算控一体化平台搭建。',
        '生成时间：'+datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')+'（香港时区）；所有数字来自当前结果文件。','',
        '## 1. 当前结论','',
        '学长提出的基础资料、ROS接口、通信与计算约束下的感知数据选择、网络通信和A2A，已在本机完成本阶段调研与模拟验收。新增480次公开图像试验、3组代理目标精确求解、7组独立容器网络测试、真实接收数据训练，以及两个独立A2A进程的11项协作/持久化检查。',
        '这不是设备验证或论文最优性证明。没有实物的条件下，设备型号、载板与JetPack只能保留为工作假设；模拟数据、代理价值和资源参数都不代表机器人真实环境。','',
        '主要发现：较简单的随机/间隔抽样在当前公开图像试验中具有较好的效果与较低的选择开销；置信度或不确定性单独排序均可能明显退化。可靠传输能送达数据，但不能保证数据仍然新鲜。A2A适合组织任务、结果与恢复查询，不是直接替代高频感知数据流的协议。','',
        '## 2. 学长要求逐项落实','',
        '| 要求 | 本阶段完成证据 | 仍需设备或真实研究验证 |','|---|---|---|',
        '| 宇树基础操作 | 核验7篇官方正文；接入与只读核查说明、模拟档案校验 | 接线、SSH、设备服务/传感器操作 |',
        '| Orin NX背景 | NX拓展坞/JetPack5.1.1工作假设，备选6.2档案，版本与IP负例检查 | 真实容量、载板、镜像、ARM/GPU速度/功耗 |',
        '| ROS1更多、ROS2也会用 | 首阶段ROS1/ROS2接口与QoS；本阶段ROS1跨独立容器通信 | 原生宇树DDS/SDK接入与ROS1适配桥 |',
        '| 通信/计算约束下选取有价值感知结果 | 实际字节预算、固定学习工作量、5种策略、3场景、5种子；精确代理目标对照 | 真实感知任务和代价模型；训练最优性 |',
        '| 网络与A2A | IP/TCP/UDP职责，容器网络、netem与抓包；真实A2A双服务委托/恢复 | 真实无线、跨机器、TLS/鉴权与进行中任务故障续跑 |','',
        '## 3. 系统结构','',
        '```mermaid','flowchart LR','  A[公开图像与模拟IMU消息] --> B[预算筛选]','  B --> C[ROS1 / TCP / UDP]','  C --> D[去重与新鲜度缓存]','  D --> E[离线标注查表与训练]','  E --> F[实验结果文件]','  G[A2A协调服务] --> H[A2A分析服务]','  F --> H','  H --> I[SQLite任务与业务结果]','```','',
        'ROS1 Master、发送端和接收端运行在3个独立容器中，无宿主公开端口。图像训练运行在Windows专用虚拟环境；A2A协调和分析服务是两个独立Windows进程，以真实回环HTTP/TCP通信。这里不是3D动力学仿真器，也没有实现机器狗运动控制。','',
        '## 4. 设备基础资料结论','',
        '学长的 module_update 是拓展坞配置页面：包含NX/Orin模组、网络接入与版本恢复等说明；不是单一通信协议教程。结合其Go2 NX出厂镜像信息，本阶段采用“Go2 EDU + NX拓展坞 + JetPack5.1.1”的假设，同时保留其他机器狗/载板可能。','',
        '实机只读核查与操作顺序见 [宇树与Orin基础操作](宇树与Orin基础操作.md)。特别区分机器人内部电脑 `.161` 和Go2拓展坞 `.18`；不能把学长说ROS1更多推导成设备底层就是ROS1。官方SDK2/DDS与ROS2资料提示，ROS1可能需要另做类型/协议适配。首阶段通用Fast DDS演示不能作为宇树CycloneDDS接入证明。','',
        '## 5. 数据与公平对照','',
        '- 使用sklearn自带UCI digits：1797张8×8手写数字图像、10类；它是真实采集的公开图像，但不是机器人相机数据。',
        '- 每种子先按源ID划分：300张公共warm start、450张测试图像、1047张流候选图像。1400条帧序列只从候选池重复抽取，重复概率0.65；源ID不跨训练/测试。',
        '- 该划分不是书写者独立划分，也不证明真实视频时序泛化。模拟IMU只作为消息元数据，未参与多模态学习；额外载荷为人工变长字段，用来检验字节预算。',
        '- 3场景：重复帧；训练流/测试图像同做1像素横向平移的感知失配；只在流标注中以20%概率加入错误标签。',
        '- 教师LogisticRegression仅用warm start训练，输出感知预测与概率；筛选函数只接收消息、像素、字节成本，不接收标签或测试集。',
        '- 接收学习器SGDClassifier(log_loss)，各策略相同600个warm start样本处理；额外学习工作预算分别800/2400个样本处理，batch40且重复采样。',
        '- 每100条消息一个字节窗口，预算比例10%/25%/50%；成本为4字节长度头+UTF8 JSON+每帧5字节模拟标注代价。',
        '- 模拟标签查表在网络接收之后提供；没有实现真实标注服务，5字节是明确统一假设，不能理解成真实标注系统完整成本。',
        '- 5种策略×3预算×2学习预算×3场景×5种子=450组；另30组全量参考，共480组。全量参考不受相同发送预算约束，也不是最优上界。','',
        '计算约束以确定的学习工作量执行，不等价于限制总CPU秒数：教师预测、选择、训练耗时分别记录，复杂选择本身可能不划算。首阶段50ms墙钟限制仍为batch间检查的软限制；本阶段没有追加硬实时保证。','',
        '## 6. 图像试验结果','',
        '以下为25%字节预算、2400个额外学习样本处理、5种子均值±标准差；选择耗时为整个1400帧流的毫秒均值，不是单帧时延。','',
        '| 场景 | 策略 | Macro F1均值±SD | 平均保留帧 | 选择耗时ms |','|---|---|---:|---:|---:|']
    for _,row in summary[(summary.ratio==.25)&(summary.learning_work==2400)].iterrows():
        lines.append(f"| {names[row.scenario]} | {names[row.strategy]} | {row.f1_mean*100:.2f}% ± {row.f1_std*100:.2f} | {row.frames_mean:.1f} | {row.selection_ms:.2f} |")
    lines.extend(['','![图像试验结果](结果/图像实验/comparison.png)','',
        '同预算指相同发送上限，不要求各策略恰好花光预算。差异/成本候选倾向选择较短消息，因此保留帧数更多；其效果仍未稳定超过随机基线。固定学习工作量控制接收训练量，但保留池的类别覆盖与重复性仍会影响模型。','',
        '与随机策略的配对差（同种子，25%预算/2400工作量）：','',
        '| 场景 | 策略 | F1差值pp | 探索性95%区间pp |','|---|---|---:|---:|'])
    for _,row in deltas[(deltas.ratio==.25)&(deltas.learning_work==2400)&(deltas.strategy.isin(['confidence','uncertainty','diverse_cost']))].iterrows():
        lines.append(f"| {names[row.scenario]} | {names[row.strategy]} | {row.paired_f1_delta_mean*100:+.2f} | [{row.ci95_low*100:+.2f}, {row.ci95_high*100:+.2f}] |")
    lines.extend(['','配对区间使用5种子t近似、未做多重比较修正，只作探索性展示。没有根据测试集重新调权重后宣称胜出；差异/成本候选的负结果保留。不同数据集上的策略排序变化说明，不能把“高置信度”或“高不确定性”当成固定训练价值。','',
        '原始结果：[逐次运行](结果/图像实验/runs.csv)、[汇总](结果/图像实验/summary.csv)、[逐窗口预算](结果/图像实验/window-budgets.csv)、[划分证据](结果/图像实验/split-manifest.json)、[配置](实验/image-config.json)。','',
        '## 7. 计算与内存','',
        f"当前480组主体运行墙钟 {metadata['wall_seconds']:.2f}s，CPU时间 {metadata['cpu_seconds']:.2f}s；按CPU时间/墙钟统计，平均约占用单个逻辑核的 {metadata['average_cpu_percent_one_core']:.2f}%。本机有 {metadata['logical_cpu_count']} 个逻辑核，这不是整台机器CPU利用率。进程峰值工作集 {metadata['peak_process_working_set_mib']:.2f}MiB，包括解释器、数据与库，非GPU显存。",'',
        '统计的是完整实验阶段的聚合CPU占用，避免将短任务Windows计时量化误当成精确CPU时延。CSV/绘图输出不计入该墙钟区间，内存峰值采样在结果整理阶段。容器CPU/内存上限是测试隔离参数，不是Orin NX的性能模拟。','',
        '## 8. “最优值”如何界定','',
        '真实研究问题可写为：在每窗口字节预算、计算预算和样本年龄约束下，选择集合S，使后续网络在独立数据上的学习效果最好。这个效果是训练过程的结果，不能在发送端用测试标签提前求值。','',
        '本阶段候选使用感知熵、像素差异和消息字节成本作为启发式。另对14条消息定义可加的整数化熵代理价值，并做精确0/1背包；3个预算都与2^14穷举一致：','',
        '| 预算比例 | 预算字节 | 精确代理目标值 | 价值/成本贪心值 | 差距 |','|---|---:|---:|---:|---:|'])
    for case in proxy['cases']:lines.append(f"| {case['ratio']:.0%} | {case['budget']} | {case['optimal_proxy_value']} | {case['greedy_proxy_value']} | {case['greedy_gap']} |")
    lines.extend(['','这只证明指定小规模、可加代理目标下的最优解；差异/成本候选本身是另一个非可加启发式，不能套用这个最优性结论。神经网络学习、分布失配、标注错误与非线性相互作用都未被代理目标精确表达。','',
        '## 9. 独立容器网络结果','',
        '实际在Linux网络命名空间间经Docker桥接传输，分别运行TCP、UDP和ROS1/TCPROS。netem在发送容器eth0出口配置基础25ms延迟、5ms抖动、12%随机包丢失、512kbit速率；不是Python随机跳过发送。规则在测试后移除。','',
        '每例最多120条已选择消息，新鲜度TTL为0.5s。消息新增发送时间字段后，重新核算JSON长度、标注假设和每窗口预算，避免时间戳开销使原选择超限。','',
        '本阶段TTL检查的是“接收时刻－发送时刻”，用来隔离传输、重试与积压造成的年龄；尚未包括真实传感器采集、前处理和筛选窗口等待的端到端样本年龄。不要把它写成完整采集至训练时限。','',
        '| 场景 | 发送 | 唯一到达 | 新鲜接受 | 过期 | 缺失 | 接收接口Ethernet字节 |','|---|---:|---:|---:|---:|---:|---:|'])
    for case in network:
        s,r=case['sender'],case['receiver'];lines.append(f"| {case['case']} | {s['selected']} | {r['unique_arrived']} | {r['accepted']} | {r['expired']} | {case['network_missing']} | {r['captured_ethernet_bytes']} |")
    reconnect=next(c for c in network if c['case']=='tcp-reconnect')
    lines.extend(['',f"TCP重连场景实际业务重试 {reconnect['sender']['application_retries']} 次，接收端去重 {reconnect['receiver']['duplicates_discarded']} 次；新鲜接受文件中没有重复训练条目。",'',
        'TCP例程有逐消息应用确认与有限重试，UDP例程无应用重传，ROS1使用发布/订阅与队列；不同发送/确认方式不支持严格吞吐排名。可靠传输可能因重传/积压而过期，因此“到达”和“可用于训练”分别统计。','',
        '接口字节来自接收容器eth0上实际抓到的双向匹配IPv4 Ethernet帧，计入捕获到的IP/TCP/UDP头、ACK及重传；排除测试控制端口。ROS1口径还含该对端间XMLRPC/TCPROS连接流量。没有Ethernet FCS、无线MAC重传或实际PHY开销，不能称为全部无线字节量。','',
        'netem出口测试用来验证故障机制，并非真实TCP性能标定；其计时粒度与TCP Small Queues等机制会影响结果，手册建议真实性能测试考虑接收端入口配置。随机丢包与调度可能改变重跑计数，不要求每次恰好缺失同样的序号。[netem手册](https://man7.org/linux/man-pages/man8/tc-netem.8.html)','',
        '网络环境共享Docker Desktop内核与时钟；没有验证真实跨设备时钟同步、天线/射频、信道干扰或移动链路。','',
        '## 10. 用实际接受的数据训练','',
        '| 场景 | 实际接受帧 | Macro F1 |','|---|---:|---:|'])
    for case,row in learning.iterrows():lines.append(f"| {case} | {int(row.actual_accepted)} | {row.macro_f1*100:.2f}% |")
    baseline=float(learning.iloc[0].baseline_f1)
    normal=float(learning.loc['tcp-normal','macro_f1'])
    lines.extend(['',f"同一warm start基线为 {baseline*100:.2f}%，正常接收120条后为 {normal*100:.2f}%，在该固定模型与输入下提高 {(normal-baseline)*100:.2f}pp。各例额外学习工作量均2400，标签按接受帧序号离线查表提供。",'',
        '这证明网络接受文件确实进入了训练，且正常协议路径给出相同数据和结果；不能从单次受损样本集合F1的上下波动推导“丢包有益”或协议优劣。模型训练在Windows完成，不是在Jetson或ROS回调线程内进行。','',
        '## 11. A2A如何接入研究','',
        '协调服务接收已知实验ID，经真实A2A SendMessage委托分析服务。分析服务读取实际接收与训练证据，返回F1、新鲜帧数、接口字节、证据哈希及限定的分析建议；它不重新选择测试集最佳策略，也不发送运动指令。','',
        f"协议1.0、官方SDK {a2a['sdk']}；官方DatabaseTaskStore配SQLAlchemy/aiosqlite。已完成11项检查：发现、真实证据委托、重复业务结果复用、SSE客户端断线后GetTask取得完成结果、取消、非法实验ID失败、两个服务的完成任务进程重启恢复、重启后缓存复用、未知方法错误和仅2次唯一业务计算。",'',
        '任务SQLite与业务结果SQLite分开：前者保存任务状态与artifact，后者按实验内容哈希避免重复业务计算。持久化测试实际终止并重新启动服务进程。','',
        '边界：验证了完成任务的重启查询，没有实现执行中的训练工作在进程崩溃后续跑；串行重复请求复用不等于分布式恰好一次执行保证。本机回环未测试TLS、用户鉴权或跨主机部署，不需LLM密钥。','',
        '## 12. 协议位置与实施判断','',
        '| 层次/用途 | 本阶段判断 |','|---|---|',
        '| IP网络层 | 负责容器/未来设备的寻址与路由；与A2A的任务语义不同 |',
        '| TCP/UDP传输 | 可靠字节流与数据报需结合时效、确认、丢弃/重试策略选择 |',
        '| ROS1数据流 | 适合复用学长已有节点；注意互相可达与消息时间/队列，而不只是Master端口 |',
        '| DDS/ROS2设备接口 | 依实际宇树类型、网卡和RMW适配；与ROS1的桥接尚未做 |',
        '| A2A任务协作 | 管理分析/训练任务、结果与状态恢复，不直接承担每帧原始感知流 |',
        '| MQTT/gRPC/Zenoh | 首阶段已比较角色，本阶段没有独立部署它们；暂不引入更多组件 |','',
        '对当前研究，先保留随机/间隔基线，明确数据价值、标注质量和计算预算，再评估新颖性/不确定性等候选是否值得额外开销。接收端应有TTL、去重、有限队列与明确的重试边界；这些机制比把某个协议名字直接当作解决方案更可验证。','',
        '## 13. 复现与审计','',
        f"独立综合审计 {audit['check_count']} 项通过：数据划分、预算、工作量、选择重放、实际网络序号与TTL、独立PCAP解析、接收训练哈希、A2A证据与磁盘任务、官方资料哈希、环境保护和容器停止。",'',
        '```powershell',"Set-Location ./simulation",'& .\\扩展调研与模拟\\复现下一阶段.ps1','```','',
        '默认复用本地官方正文快照；需要重新访问官方资料时加 `-RefreshOfficialDocs`。脚本会更新新阶段结果并据此重新生成本报告；数据固定种子结果应重现，计时/网络随机故障结果允许变化。只操作本项目服务，不全局清理Docker，不改现有Ubuntu。','',
        '环境清单：[实际版本](环境/environment-manifest.json)、[数据依赖](环境/requirements-data.lock.txt)、[A2A依赖](环境/requirements-a2a.lock.txt)。',
        f"当前新网络镜像ID：`{env['images'][1]['id']}`；节点脚本从项目只读挂载执行，实际镜像和配置已记录。物理设备部署版本仍未知。",'',
        '## 14. 下周计划','',
        '目前尚未接触机器狗或Jetson实物。下周工作以资料研读、公开/合成数据分析和电脑端模拟仿真为主，不安排设备接线、实机操作、真实传感器采集或真实无线测试。','',
        '| 方向 | 工作计划 | 预期产出 |','|---|---|---|',
        '| 通信协议与系统架构 | 继续梳理单智能体内部的ROS 1/ROS 2、TCPROS、DDS/RTPS、消息接口与网络传输关系；进一步研究A2A在智能体任务协作中的职责，并与高频感知数据流区分 | 分层通信架构图、模块交互图、协议职责及适用场景对照表 |',
        '| 多模态数据流模拟 | 在电脑上构造相机特征、模拟IMU/点云元数据与时间戳，明确哪些字段来自公开数据、哪些为合成数据；研究消息字段、单位、坐标系和同步假设 | 可复现的模拟数据说明、消息契约草案、数据同步与划分规则 |',
        '| 通信/计算预算下的数据选择 | 在当前数据选择实验基础上扩展策略或场景，对比全量、随机/间隔与价值筛选；同时统计消息字节、数据年龄、处理开销和训练指标，不预设复杂策略一定有效 | 多种子模拟结果、预算与指标对照、适用边界和失败案例 |',
        '| ROS与网络条件仿真 | 使用本机隔离进程/容器传递模拟消息，研究队列、TTL、丢包、延迟与重连对接收数据的影响；ROS 1与ROS 2分别按其接口和QoS机制分析 | 可重放的本机仿真、关键配置、消息流及异常场景结果 |',
        '| A2A协作模拟与总结 | 用规则型本机服务模拟分析任务委派、状态查询、重复请求与故障恢复；归纳A2A与ROS感知链路的职责边界 | A2A交互示例、通信方案比较和阶段性研究总结 |','',
        '下周产出均为文献调研、公开/合成数据实验和电脑端模拟结果，不代表真实设备配置、硬件性能、无线表现或真实训练收益。设备型号、JetPack、原生接口及实物数据将在具备条件后再核实；通信分层见[网络调研](../网络调研.md)，引用来源见[资料索引](资料索引.md)。','',
        '详细参考资料见 [资料索引](资料索引.md)。'])
    (ROOT/'综合模拟报告.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    references=['# 本阶段资料索引','','核验日期：2026-10-04。官方页面正文摘要用于调研；完整本地快照仅作私有核验，不上传。','',
        '| 官方宇树资料 | 页面更新时间 | 证据边界 |','|---|---|---|']
    for doc in docs:references.append(f"| [{doc['name']}]({doc['public_page']}) | {doc['page_update_time']} | 官方CDN正文已读取，哈希见结果/宇树官方资料核验.json；不代表实机验证 |")
    references.extend(['','其他依据：','',
        '- [NVIDIA JetPack5.1.1版本说明](https://docs.nvidia.com/jetson/jetpack/5.1.1/release-notes/index.html)：Ubuntu20.04/L4T35.3.1版本关系。',
        '- [NVIDIA JetPack6.2版本说明](https://docs.nvidia.com/jetson/jetpack/6.2/release-notes/index.html)：备选Orin软件环境。',
        '- [NVIDIA Orin NX载板适配](https://docs.nvidia.com/jetson/archives/r36.5/DeveloperGuide/HR/JetsonModuleAdaptationAndBringUp/JetsonOrinNxNanoSeries.html)：模组和载板区分。',
        '- [Unitree ROS2固定提交README](https://github.com/unitreerobotics/unitree_ros2/blob/668d1ec5a05d1c38d3306bdca7d59f2ba3581a88/README.md)：DDS/RMW、版本、类型与网卡要求；未部署宇树消息包。',
        '- [Open Robotics Noetic生命周期](https://discourse.ros.org/t/ros-noetic-end-of-life-may-31-2025/43160)：2025-05-31结束支持。',
        '- [sklearn load_digits](https://scikit-learn.org/stable/modules/generated/sklearn.datasets.load_digits.html)：1797张8×8图像、10类，源自UCI；本轮按源ID重新划分，非机器人数据。',
        '- [UCI原数据介绍](https://archive.ics.uci.edu/dataset/80/optical+recognition+of+handwritten+digits)：原始数据来源，未使用完整训练包。',
        '- [RFC9293 TCP](https://www.rfc-editor.org/rfc/rfc9293.html)、[RFC768 UDP](https://www.rfc-editor.org/rfc/rfc768.html)：传输语义背景。',
        '- [netem手册](https://man7.org/linux/man-pages/man8/tc-netem.8.html)：内核延迟/丢包/限速及计时、TCP出口测试限制。',
        '- [A2A官方规范](https://a2a-protocol.org/latest/specification/)：协议1.0交互范围。',
        '- [官方Python SDK v1.2.1 DatabaseTaskStore](https://github.com/a2aproject/a2a-python/blob/v1.2.1/src/a2a/server/tasks/database_task_store.py)：实际使用的官方数据库任务存储，源码固定到版本tag而非提交；安装包版本另在锁清单中。','',
        '早期ROS/DDS、MCP、gRPC、MQTT、Zenoh等来源与边界保留在 [首阶段索引](../资料索引.md)。本阶段不以未部署的候选协议宣称性能优势。'])
    (ROOT/'资料索引.md').write_text('\n'.join(references)+'\n',encoding='utf-8')
    report_rows=summary[(summary.ratio==.25)&(summary.learning_work==2400)]
    figdata=report_rows[['scenario','strategy','f1_mean','selection_ms']]
    figdata.to_csv(ROOT/'结果/报告关键表.csv',index=False)
    print(json.dumps({'report_generated':True,'lines':len(lines),'audit_checks':audit['check_count']}))

if __name__=='__main__':main()
