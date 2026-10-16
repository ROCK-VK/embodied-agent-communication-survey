# UART-only benchmark

独立ESP32-C5固件，不初始化Wi-Fi。UART0/PLL_F80M/8N1，安全921600 READY；SET_BAUD双向ACK/BAUD_READY后START wire_rate seconds payload_len。UB8C16B头+确定payload+CRC32 IEEE4B；serial包含控制FINAL，数据记录1024B时payload1004B。

tools/benchmark_host.py实测3M 250KB/s×30s和280KB/s×30s均零丢/CRC/序号/resync/格式错误，实际约249938/279931Bps。只表示当前COM10/CH343/USB环境30秒工程窗口，不是持续任意负载保证。STOP确认、COM关闭，之后已烧录8c，不再是板上当前app。
