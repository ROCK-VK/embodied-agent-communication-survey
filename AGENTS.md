# GitHub成果同步规则

- 用户持续授权每次完成有效修改/实验后commit并push到本仓库main；验证与日志同步先于推送，远端核对后才能宣布同步完成。失败时保留待推送commit和原因，不force push覆盖。
- 本地阶段工作与原始证据仍位于仓库旁工作记录/3-CSI调研与实机验证；先恢复该阶段日志/项目当前状态.md，按需查执行记录。csi/是公开白名单副本，不替代本地持久化日志。
- 不上传凭据、sdkconfig/带凭据固件、原Flash、原始串口/SSH输出或生成依赖。公开阶段副本匿名化SSID/MAC/私网地址；发布脚本位于本地第三阶段发布到GitHub.py。
- 当前路线ESP32-C5 / Pi4B Nexmon CSI / AX210 PicoScenes；Atheros历史备用，FeitCSI退出主方案。C5 router基线已通过，其余验证等级以最新结果为准。
- 不因发布任务操作Jetson或其他硬件；保护现有网络/服务。
