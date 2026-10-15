# GitHub成果同步规则

- 用户持续授权每次完成有效修改/实验后commit并push到本仓库main；验证与日志同步先于推送，远端核对后才能宣布同步完成。失败时保留待推送commit和原因，不force push覆盖。
- 本地阶段工作与原始证据仍位于仓库旁工作记录/3-CSI调研与实机验证；先恢复该阶段日志/项目当前状态.md，按需查执行记录。csi/是公开白名单副本，不替代本地持久化日志。
- 不上传凭据、sdkconfig/带凭据固件、原Flash、原始串口/SSH输出或生成依赖。公开阶段副本匿名化SSID/MAC/私网地址；发布脚本位于本地第三阶段发布到GitHub.py。
- 当前路线ESP32-C5 / Pi4B Nexmon CSI / AX210 PicoScenes；Atheros历史备用，FeitCSI退出主方案。C5 router与被动Jetson legacy上行CSI PoC已通过；完整导出/全PHY/业务关联/Pi未验证。
- 不因发布任务操作Jetson或其他硬件；保护现有网络/服务。

- 仓库根README以当前CSI任务为主；旧协议报告、docs与simulation位于归档/，只作历史参考。维护链接及发布脚本时使用归档/simulation的新路径，不把旧阶段重新置为当前任务。

## 主Agent与子Agent协作偏好（用户2026-10-15授权）

- 主Agent负责目标澄清、任务拆分、关键决策、验收整合和最终交付。用户在界面选择GPT-6.1 Sol（gpt-6.1-sol），主Agent思考深度由用户自行调整medium/high等；项目规则不等于已修改/锁定应用模型，不自行改用户全局设置。
- 用户持续授权按需派子Agent处理可独立拆分的工作，无需每次再次询问；简单工作主Agent直接完成，不为并行而并行。
- 所有新派子Agent明确指定model=gpt-6-luna、reasoning_effort=max；当前工具要求跨模型派生使用fork_turns=none，因此必须主动提供任务上下文、日志/文件入口、约束和验收条件，不假设自动继承聊天。
- 若该模型/深度不可用，说明实际限制，不静默换其他模型或档位；下级派生同样遵守此偏好。
- 主Agent复核子Agent结果后再写最终结论；子任务分配明确文件/范围，避免同时改同一文件。硬件端口/SSH/烧录等操作串行协调，既有Jetson保护和发布规则对所有Agent生效。
