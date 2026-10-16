// UART-only firmware. No Wi-Fi initialization, callbacks, scan or capture.
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "esp_vfs_dev.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "esp_rom_crc.h"
#include "esp_rom_sys.h"
static uint8_t wire[4116];
static void p16(uint8_t*p,unsigned v){p[0]=v;p[1]=v>>8;}
static void p32(uint8_t*p,uint32_t v){for(int i=0;i<4;i++)p[i]=v>>(i*8);}
static unsigned emit(unsigned kind,unsigned serial,const uint8_t *p,unsigned n){
 memcpy(wire,"UB8C",4);wire[4]=1;wire[5]=kind;p16(wire+6,16);p32(wire+8,serial);p32(wire+12,n);
 if(p!=wire+16)memcpy(wire+16,p,n);
 p32(wire+16+n,esp_rom_crc32_le(0,wire,16+n));
 int w=uart_write_bytes(UART_NUM_0,wire,n+20);return w==(int)(n+20)?0:1;
}
void app_main(void){
 esp_log_level_set("*",ESP_LOG_NONE);setvbuf(stdout,NULL,_IONBF,0);
 uart_config_t c={.baud_rate=921600,.data_bits=UART_DATA_8_BITS,.parity=UART_PARITY_DISABLE,.stop_bits=UART_STOP_BITS_1,.flow_ctrl=UART_HW_FLOWCTRL_DISABLE,.source_clk=UART_SCLK_PLL_F80M};
 ESP_ERROR_CHECK(uart_param_config(UART_NUM_0,&c));ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0,2048,16384,0,NULL,0));esp_vfs_dev_uart_use_driver(UART_NUM_0);
 uint32_t actual=0;ESP_ERROR_CHECK(uart_get_baudrate(UART_NUM_0,&actual));
 printf("{\"event\":\"READY\",\"version\":\"uart-benchmark-8c\",\"baud\":%u,\"clock\":\"PLL_F80M\",\"wifi_initialized\":false}\n",(unsigned)actual);
 char line[160];unsigned baud,rate,seconds,n;
 while(1){
  if(!fgets(line,sizeof(line),stdin)){vTaskDelay(1);continue;}
  if(sscanf(line,"SET_BAUD %u",&baud)==1&&(baud==3000000||baud==2500000||baud==2000000||baud==921600)){
   printf("{\"event\":\"BAUD_ACK\",\"requested\":%u}\n",baud);uart_wait_tx_done(UART_NUM_0,pdMS_TO_TICKS(2000));vTaskDelay(pdMS_TO_TICKS(150));
   ESP_ERROR_CHECK(uart_set_baudrate(UART_NUM_0,baud));ESP_ERROR_CHECK(uart_get_baudrate(UART_NUM_0,&actual));
   printf("{\"event\":\"BAUD_READY\",\"requested\":%u,\"actual\":%u}\n",baud,(unsigned)actual);
  }else if(sscanf(line,"START %u %u %u",&rate,&seconds,&n)==3&&rate>0&&rate<300000&&seconds>0&&seconds<=60&&n>0&&n<=4096){
   unsigned total=(uint64_t)rate*seconds/(n+20),errors=0;
   for(unsigned i=0;i<n;i++)wire[16+i]=(i*17+23)&255;
   printf("{\"event\":\"START_ACK\",\"expected\":%u,\"wire_size\":%u}\n",total,n+20);uart_wait_tx_done(UART_NUM_0,pdMS_TO_TICKS(2000));
   int64_t start=esp_timer_get_time();
   for(unsigned i=0;i<total;i++){
    int64_t deadline=start+(int64_t)i*(n+20)*1000000/rate;
    while(esp_timer_get_time()<deadline){int64_t rem=deadline-esp_timer_get_time();if(rem>2000)vTaskDelay(1);else if(rem>0)esp_rom_delay_us((unsigned)rem);}
    errors+=emit(1,i+1,wire+16,n);
   }
   uart_wait_tx_done(UART_NUM_0,pdMS_TO_TICKS(5000));int64_t elapsed=esp_timer_get_time()-start;
   char final[256];int z=snprintf(final,sizeof(final),"{\"event\":\"FINAL\",\"expected\":%u,\"write_errors\":%u,\"elapsed_us\":%lld,\"bytes\":%u,\"free_heap\":%u,\"min_free_heap\":%u}",total,errors,(long long)elapsed,total*(n+20),(unsigned)esp_get_free_heap_size(),(unsigned)esp_get_minimum_free_heap_size());
   emit(2,total+1,(uint8_t*)final,z);uart_wait_tx_done(UART_NUM_0,pdMS_TO_TICKS(5000));
  }else if(!strncmp(line,"STOP",4)){printf("{\"event\":\"STOPPED\"}\n");}
  else printf("{\"event\":\"ERROR\"}\n");
 }
}
