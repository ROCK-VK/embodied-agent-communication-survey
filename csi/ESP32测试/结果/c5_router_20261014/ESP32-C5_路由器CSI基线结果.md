# ESP32-C5 路由器CSI基线结果（2026-10-14）

状态：**已完成本板路由器CSI基线实机测试**。范围为AP→ESP；没有测试Jetson监听、ESP AP业务或sample_id关联。只修改/烧录测试ESP，未SSH或改变Jetson、Windows Wi-Fi、路由器配置。

## 版本与链路

- 用户板：QSZNTEC标识；实查ESP32-C5 revision v1.0，Flash4MB（manufacturer46/device4016），BASE MAC <ESP_BASE_MAC>；具体板SKU/天线规格仍未确认。
- 入口：UART Type-C→CH343/COM10→Windows，应用串口921600。
- ESP-IDF5.5.5、esptool4.12.0；esp-csi8633d67152db2808f141cc1595970aa9cf406045，cmake_utilities0.5.3、esp_csi_gain_ctrl0.1.5，锁文件已保存。
- 原版csi_recv_router应用源码与固定ZIP字节一致；只设置本地SSID/密码/Flash配置。CMake项目名CSI_Router来自路径入口，不代表换例程。
- 原Flash全量4MB备份及SHA256保存。构建/分区大小检查通过；bootloader/partition/app烧录Hash校验通过。串口ELF hash前缀7636c6df0与构建ELF完整SHA256一致，版本见manifest。
- AP：<TEST_AP_SSID>，BSSID<AP_BSSID>，5GHz149。ESP关联日志直接显示**BW20**，IPv4 <ESP_IP>，gateway<AP_GATEWAY>。密码只在本地sdkconfig/产物，不写报告。

## 实测统计

| 项目 | 结果 |
|---|---|
| 主机采集窗口 | 300.03秒，含启动/联网约15秒 |
| 首条至末条CSI本地timestamp跨度 | 285.141275秒 |
| CSI记录数 | 28861 |
| 基于CSI时间跨度的观察记录率 | 101.213条/秒；不是逐包业务匹配率或性能保证 |
| 来源MAC | 全部<AP_BSSID>（AP BSSID） |
| channel | 全部149 |
| CSV len | 本次全部106，均等于输出数组元素数；不是其他PHY的通用合法长度 |
| rx_format原始值 | 本次全部1，未额外标定该值与每包PHY语义 |
| first_word_invalid | 本次全部0 |
| RSSI | -61至-37dBm，中位数-45dBm |
| 解析错误/数组长度不匹配 | 0 / 0 |
| 本地seq中断/回绕 | 0，seq为0至28860；不是802.11序号/Ping序号 |
| 全零输出数组 | 0；非零不等于channel estimate有效 |
| rx_channel_estimate_info_vld/rx_state有效率 | 原版未导出，未知 |

原版AP BSSID过滤仍在，数据是AP→ESP CSI。不能把28861条当Ping回复数、Jetson上行数或UDP业务数；本次未抓原始Wi-Fi frame，不能计算无线CSI覆盖率。应用期CSI行可解析且连续；原始文件开始保留ROM阶段不同串口波特率产生的乱码，不计为应用CSI解析错误。

## 构建失败经验与恢复

1. idf.py将junction realpath还原中文路径，kconfgen按GBK读UTF8失败；本进程PYTHONUTF8=1后配置通过。
2. ccache中文路径filesystem转换失败；本次禁用缓存后C/C++编译通过。
3. objdump对真实中文绝对库路径退出；直接CMake -S D:/CSI_Router -B D:/CSI_Build后ldgen通过。
4. 组件管理器仍把gain_ctrl预编译库路径还原中文，ld返回5；只修正生成build.ninja/link rsp里的该例程路径为等价ASCII junction后链接成功。应用源码/组件二进制未改。未来重新生成可能再次需要此路径适配。

实际文件仍在第三阶段ESP32测试下；D:/CSI_Work、D:/CSI_Router、D:/CSI_Build均为路径入口。构建日志build.log/build_no_ccache.log/build_ascii.log/build_link_fix.log保留失败到成功的证据。未重装IDF、改全局Anaconda/PATH或安装USB驱动。

## 文件与后续

- serial_raw.log：原始串口记录；capture_summary.json、analysis_summary.json：统计；manifest.json：硬件/版本/固件与原文hash；flash.log：烧录结果。
- original_flash_4MB.bin/.sha256：原板完整备份，不默认公开。
- ../../capture_router.py、../../analyze_router.py：采集/离线统计脚本；当前统计已由实际记录验证。
- 采集进程已结束并释放COM10；重新打开/关闭端口确认可用。**板上router例程仍运行**，仍可能继续Ping AP。
- 下一步是独立promiscuous固件与受控窄带第三方TX验证；当前Jetson网络保持原状。AP报告BSS80MHz但C5协商BW20，不证明能采Jetson VHT80上行。
- 尚未做2.4GHz/20MHz基线、Jetson监听、ESP AP普通STA、valid字段增强、payload/sample_id关联、Pi/Nexmon或传感器集成。
