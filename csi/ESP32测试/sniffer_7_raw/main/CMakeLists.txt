idf_component_register(SRCS "sniffer.c" INCLUDE_DIRS "." REQUIRES esp_wifi esp_event esp_netif nvs_flash esp_driver_uart vfs esp_timer)
