# CSI 调研与实机验证

更新：2026-10-14。本目录是本地第三阶段工作的公开副本；现场SSID、MAC与私网地址已匿名化，占位符不能原样用来连接设备。完整原始证据及持久化项目日志在本地保留。

## 当前路线和结果

- ESP32-C5：现有1块QSZNTEC标识开发板，实查revision v1.0/Flash4MB、CH343/COM10。固定IDF5.5.5+esp-csi8633d67152db2808f141cc1595970aa9cf406045已完成官方router基线。
- 实测：5GHz/149，C5协商BW20；300.03秒含约15秒启动联网，28861条AP→ESP CSI，首末CSI跨度285.141275秒，观察记录率101.213条/秒。解析/数组长度错误和本地seq中断均0；原版未导出channel-estimate valid，有效率尚未知。
- Pi4B Nexmon CSI：保留第二条正式路线，系统/firmware门禁先于部署，尚未在本项目复现。
- AX210 PicoScenes：x86原生Linux升级路线；不在Jetson ARM、Pi ARM或WSL部署。FeitCSI退出主方案，Atheros保持历史参考/备用。
- 后续：单板router→独立promiscuous探索→ESP AP备选（先PC，未来Jetson）→sample_id关联→传感器。Jetson网络/驱动/服务保持现状；VHT80仍为高可信推断。

最新SSH只读复核（2026-10-14 15:48）：认证及hostname命令成功，新增会话已退出；设备配置保持现状。

## 阅读入口

- [ESP32-C5单板测试方案](ESP32_CSI测试方案.md)
- [Pi4B Nexmon测试方案](树莓派4B_Nexmon_CSI测试方案.md)
- [当前三路线与PoC边界](CSI当前路线与PoC验证.md)
- [Jetson只读补查](Jetson只读补查_2026-10-13.md)、[网络和扩展接口报告](Jetson网络与扩展接口只读确认_2026-10-13.md)
- [C5 router实测报告](ESP32测试/结果/c5_router_20261014/ESP32-C5_路由器CSI基线结果.md)
- [串口采集脚本](ESP32测试/capture_router.py)、[离线统计脚本](ESP32测试/analyze_router.py)
- [采集统计](ESP32测试/结果/c5_router_20261014/capture_summary.json)、[离线统计](ESP32测试/结果/c5_router_20261014/analysis_summary.json)、[版本/产物哈希](ESP32测试/结果/c5_router_20261014/manifest.json)
- [公开更新记录](更新记录.md)、[此前模拟成果](../simulation/README.md)

## 复现边界

源码使用Espressif固定commit的csi_recv_router，不另发布第三方源码副本。设置自己的SSID/密码后先纯build再flash；Windows优先使用纯英文构建路径，原实验中文路径的失败/修复过程见报告。公开采集脚本仅依赖pyserial，运行会复位测试ESP，默认COM10/921600；300秒后释放端口，固件仍运行。

本仓库不包含sdkconfig、带Wi-Fi凭据的固件、原Flash备份、原始串口/SSH输出、安装器或源码ZIP。公开统计不能替代原始帧复核，也不宣称UDP=Wi-Fi帧=CSI、Jetson监听已成功或所有记录物理有效。

用户已持续授权：每次完成有效修改或实验后，同步本地日志、验证公开白名单副本、commit/push并核对远端；推送失败需明确报告，不强推覆盖。

## 实验2最新结果

[被动监听结果D](ESP32测试/结果/c5_sniffer_jetson_20261014_online_v3/ESP32-C5_被动监听Jetson_PoC结果.md)：在线300秒目标FRAME43915（Data470）、CSI目标43915；落盘有效上行DataCSI311，241组同帧元数据确认。仅legacy OFDM，不是VHT80 CSI。UART queue drop与1条JSON错误已量化，完整覆盖未验证；Agent未改Jetson，当前不进入AP Plan B。

[独立固件与核验](ESP32测试/sniffer_jetson/联网核验与实现说明.md)、[采集脚本](ESP32测试/sniffer_jetson/capture_sniffer.py)。初次目标关机的零结果不作能力判断；本轮结束ESP CSI/prom已STOP，COM已释放。
