# sniffer-8d-a：Promiscuous Full Filter 单变量 RF 诊断报告

- 日期：2026-10-19
- 固件版本：`sniffer-8d-a-full-filter`（基于 8c staged architecture 复制的独立工程）
- 测试目的：单变量验证恢复 Promiscuous Full Filter（`MGMT | CTRL | DATA | MISC`）是否能恢复射频 CSI callback。
- 执行原则：**严格被动监听，Jetson 保持原 2.4GHz WLAN 连接，全程不断网、不重关联、不发 UDP、不做解密。**

---

## 1. 单变量修改与基线对比

为实现严格单变量 A/B，本版本仅作**唯一一处影响 RF 行为的改动**：

| 维度 | 8c 历史实机（commit `5b6d417`） | 8d-a 本次实机（`run1` & `run2`） | 变量属性 |
|---|---|---|---|
| **Promiscuous Filter** | `WIFI_PROMIS_FILTER_MASK_DATA` (仅 DATA) | `MGMT \| CTRL \| DATA \| MISC` (全掩码) | **唯一 RF 实验变量** |
| 信道配置顺序 | `esp_wifi_start -> set_ps -> set_band_mode -> set_channel` | 保持 8c 原样 | 控制变量（未变） |
| 动态 Mode 状态机 | `change_mode()` 动态 toggle prom & CSI | 保持 8c 原样 | 控制变量（未变） |
| CSI 配置 | legacy/ht20/ht40/vht/su/mu/dcm/beamformed/he_stbc 全开 | 保持 8c 原样 | 控制变量（未变） |
| CSI 回调注册 | 紧随 filter 注册 | 保持 8c 原样 | 控制变量（未变） |
| 传输波特率 | 3,000,000 baud（带安全 921600 握手） | 保持 8c 原样 | 控制变量（未变） |
| 业务候选过滤 | API payload <= 256B 判定候选，大帧主动过滤 | 保持 8c 原样 | 控制变量（未变） |
| 纯观测代码增加 | STATS JSON 中未导出 prom 分类统计 | 增加 prom 分类、CSI 逐级、PHY 格式统计及信道读回 | **纯观测变量（不改变 RF 行为）** |

---

## 2. 两次被动监听实测数据（实机证据）

烧录 `sniffer-8d-a-full-filter.bin`（Hash verified）后，在信道 2 上针对目标 Jetson ↔ AP 执行两轮连续被动监听：

| 指标项 | 8c 历史实机 | 8d-a 第一轮（30.0s 被动） | 8d-a 第二轮（15.0s 重复验证） |
|---|---:|---:|---:|
| **实际信道读回（actual / expected）** | 未做读回 | 2 / 2（`readback_ok=True`） | 2 / 2（`readback_ok=True`） |
| **实际 Wi-Fi 模式** | 未做读回 | `WIFI_MODE_NULL` (0) | `WIFI_MODE_NULL` (0) |
| **Promiscuous Callback 总数** | 漏导出 | **3,130** | **1,487** |
| ├─ Management 帧 | 漏导出 | 2,906 | 1,403 |
| ├─ Control 帧 | 漏导出 | 0 | 0 |
| ├─ Data 帧 | 漏导出 | 222 | 82 |
| └─ Misc 帧 | 漏导出 | 2 | 2 |
| **CSI Callback 总数（`csi_cb_total`）** | **0** | **1,544** | **851** |
| ├─ 目标 Jetson 来源（`csi_source_target`） | 0 | **128** | **76** |
| ├─ 非目标设备来源（`csi_source_other`） | 0 | 1,416 | 775 |
| ├─ 包含有效 Header（`csi_hdr_present`） | 0 | 128 | 76 |
| ├─ 包含有效 CSI Buffer（`csi_buf_present`） | 0 | 128 | 76 |
| ├─ 信道估计有效（`vld=1`） | 0 | 128 | 76 |
| ├─ 接收状态正常（`rxstate=0`） | 0 | 128 | 76 |
| └─ **目标有效 CSI（`csi_target_valid`）** | **0** | **128** | **76** |
| **PHY 调制格式分布** | | | |
| ├─ 802.11b（`cur_bb_format=0`） | 0 | 0 | 0 |
| ├─ Legacy OFDM（`cur_bb_format=1`） | 0 | 1,171 | 669 |
| └─ **802.11n HT（`cur_bb_format=2`）** | **0** | **373** | **182** |
| **PROBE 业务候选过滤行为** | | | |
| ├─ 大背景帧主动过滤（`large_frame_filtered`） | 0 | 126 | 75 |
| ├─ 小候选帧导出（`candidate_seen`） | 0 | 2 | 1 |
| └─ 导出的原子 `CSI_DATA` 记录数 | 0 | 2 | 1 |
| **系统与传输资源** | | | |
| ├─ 队列丢弃（`queue_drop`） | 0 | **0** | **0** |
| ├─ 串口写错误（`write_errors`） | 0 | **0** | **0** |
| ├─ 队列高水位（`high_water`） | 1 / 24 | **1 / 24** | **1 / 24** |
| ├─ 最低空闲堆内存（`min_free_heap`） | 102,184 B | **104,356 B** | **106,900 B** |
| └─ 截断/冲突/CRC/序号错误 | 0 | 全部 0 | 全部 0 |

---

## 3. 结果判定与严格科学结论

1. **A/B 判定结论**：
   在其余 8c RF 行为（调用顺序、信道配置时序、动态使能逻辑、staged architecture）保持完全不变时，仅仅将 promiscuous filter 由 `DATA-only` 恢复为 `full mask`（`MGMT | CTRL | DATA | MISC`）后，CSI callback 立即从 **0** 恢复到 **1,544**（第一轮）和 **851**（第二轮），目标有效 HT CSI 从 0 恢复至 **128** 和 **76**。
   **因此，filter 范围是目前最强支持的关键变量。**

2. **科学措辞声明**：
   本实机实验确证了“full promiscuous filter 恢复与 CSI callback 恢复之间存在直接强因果关联”，但**不宣称“已经证明 ESP CSI 底层引擎具体依赖 MGMT/CTRL/MISC 中的哪一种”**。底层硬件基带的信道估计具体机制属于厂家黑盒，目前无须也不应过度推测。

3. **后续分支判定**：
   - 因为 8d-a 两次被动窗口均稳定恢复且各项资源极佳，**无需执行 8d-b**（无需修改初始化顺序）。
   - **无需烧录历史 8b 进行额外 A/B**。
   - **无需执行受控上行激发**。

4. **状态保持**：
   测试完成后，ESP 已接收 `MODE STOP` 并确认 `FINAL`，COM10 串口正常关闭；Jetson 保持原连接、原信道、原 IP 与 SSH 连通，全程无任何网络中断。
