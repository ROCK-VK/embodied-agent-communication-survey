# 机器狗 Wi-Fi CSI 采集与验证

当前任务：复用 Jetson 的 RTL8821CU 作为普通 Wi-Fi 发送端，由固定接收节点采集 CSI；先确认来源与采集质量，再研究业务样本、时间和位姿关联。

更新时间：2026-10-14。此前通信协议、ROS/DDS、网络/A2A及感知数据选择模拟成果已移入[归档](归档/README.md)。

## 当前进展

| 实验 | 状态与证据 | 范围 |
|---|---|---|
| ESP32-C5单板 Router baseline | 已通过；5GHz/149、C5协商BW20，5分钟窗口28861条CSI | AP→ESP；不代表Jetson监听 |
| ESP32-C5被动监听Jetson | 已通过D；目标帧43915次（Data470），CSI目标43915次；落盘有效上行DataCSI311条，241组同帧元数据确认 | Jetson→ESP的legacy OFDM上行数据；不是VHT80 CSI或完整覆盖 |
| Pi4B + Nexmon CSI | 方案与版本门禁已整理，尚未部署验证 | 待实机 |
| packet_id/sample_id、传感器时间与位姿关联 | 尚未执行 | CSI存在性不等于业务关联 |

实验2保持Jetson原Wi-Fi与eth0配置、ROS和服务不变，ESP以NULL模式监听149，经UART导出。首次目标关机的零结果不计为能力失败；开机复核后的正结果单独保存。

当前限制：密集控制帧使UART文本导出出现队列丢弃及1条JSON解析错误。回调计数和落盘数分开统计，不能将导出丢失视为空口CSI缺失率，也不能宣称一条UDP=一帧Wi-Fi=一条CSI。

## 当前路线

1. **ESP32-C5 + Espressif esp-csi**：当前主验证路线，已有1块C5 v1.0/4MB板，固定ESP-IDF5.5.5。
2. **Raspberry Pi 4B + Nexmon CSI**：后续固定CSI节点路线；先核对OS/kernel/firmware，再按维护者流程部署。
3. **Intel AX210 + x86 Linux + PicoScenes**：按需升级路线；原生x86平台，不部署在Jetson ARM、树莓派ARM或WSL。

Atheros CSI Tool仅作历史参考/备用；FeitCSI已退出当前主方案。当前无需进入ESP AP Plan B或切换Jetson网络。

## 阅读与代码入口

- [CSI阶段总览](csi/README.md)、[三路线与PoC边界](csi/CSI当前路线与PoC验证.md)
- [ESP32-C5测试方案](csi/ESP32_CSI测试方案.md)、[Pi4B Nexmon测试方案](csi/树莓派4B_Nexmon_CSI测试方案.md)
- [Router基线报告](csi/ESP32测试/结果/c5_router_20261014/ESP32-C5_路由器CSI基线结果.md)
- [实验2被动监听报告](csi/ESP32测试/结果/c5_sniffer_jetson_20261014_online_v3/ESP32-C5_被动监听Jetson_PoC结果.md)
- [独立监听固件](csi/ESP32测试/sniffer_jetson/main/sniffer.c)、[UART采集脚本](csi/ESP32测试/sniffer_jetson/capture_sniffer.py)、[联网核验与实现说明](csi/ESP32测试/sniffer_jetson/联网核验与实现说明.md)
- [Jetson只读盘点](csi/Jetson只读补查_2026-10-13.md)、[网络/扩展接口](csi/Jetson网络与扩展接口只读确认_2026-10-13.md)
- [公开更新记录](csi/更新记录.md)、[历史阶段归档](归档/README.md)

## 下一步

- 优先减少控制帧导出、保留全量计数并优先输出Data，评估队列/二进制记录，重新验证导出损失。
- 准备Pi4B的专用系统、管理通道和版本门禁；按独立方案执行。
- 按需开展20MHz普通STA对照和PHY覆盖研究；目前现场缺对照设备。
- 采集质量明确后再研究业务标识和时间/位姿关联，不提前接入相机、雷达大流量。

## 仓库结构与发布范围

```text
csi/       当前CSI方案、独立代码、匿名结果与更新记录
归档/      此前协议调研、资料索引、模拟代码与结果
```

公开文档、独立代码、匿名统计和版本/产物哈希；现场SSID/MAC/私网地址已匿名化，占位符需替换才能复现。不上传密码、带凭据配置/固件、原Flash、敏感原始日志或生成依赖。每次完成有效工作后同步日志、commit/push并核对远端。
