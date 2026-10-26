// Real RF path and explicitly marked synthetic engineering path share callbacks.
#include "capture_core.inc"
static atomic_bool synth_task_running;
static void synth_task(void *arg){
 (void)arg;
 static uint8_t frame[1700],csibuf[114];
 static uint8_t epstore[sizeof(wifi_pkt_rx_ctrl_t)+256] __attribute__((aligned(4)));
 wifi_csi_info_t p={0};p.hdr=frame;p.payload=frame+24;p.buf=(int8_t*)csibuf;p.len=114;
 memcpy(p.mac,target,6);memcpy(p.dmac,ap,6);p.rx_ctrl.rx_channel_estimate_info_vld=1;p.rx_ctrl.rx_state=0;p.rx_ctrl.channel=2;p.rx_ctrl.cur_bb_format=2;p.rx_ctrl.rssi=-40;
 for(unsigned j=0;j<114;j++)csibuf[j]=(j*3+5)&255;
 unsigned total=synth_rate*synth_seconds;int64_t start=esp_timer_get_time();
 for(unsigned i=0;i<total&&atomic_load(&synthetic_active);i++){
  int64_t due=start+(int64_t)i*1000000/synth_rate;
  while(esp_timer_get_time()<due){int64_t d=due-esp_timer_get_time();if(d>2000)vTaskDelay(1);else if(d>0)esp_rom_delay_us(d);}
  for(unsigned j=0;j<sizeof(frame);j++)frame[j]=(j*7+11)&255;
  put16(frame,0x4188);memcpy(frame+4,ap,6);memcpy(frame+10,target,6);memcpy(frame+16,ap,6);put16(frame+22,(i&4095)<<4);put16(frame+24,0);
  p.payload_len=128;p.rx_seq=i&65535;p.rx_ctrl.sig_len=128;p.rx_ctrl.dump_len=132;p.rx_ctrl.timestamp=(uint32_t)esp_timer_get_time();csi_cb(NULL,&p);atomic_fetch_add(&synthetic_candidates,1);
  for(unsigned j=0;j<4;j++){p.payload_len=1500;p.rx_ctrl.sig_len=1500;p.rx_ctrl.dump_len=1504;csi_cb(NULL,&p);atomic_fetch_add(&synthetic_large,1);}
  if(i%synth_rate==0){
   unsigned msg=(i/synth_rate)%4+1;wifi_promiscuous_pkt_t *ep=(void*)epstore;memset(epstore,0,sizeof(epstore));
   bool down=msg==1||msg==3;uint8_t *b=ep->payload;put16(b,down?0x0208:0x0108);memcpy(b+4,down?target:ap,6);memcpy(b+10,down?ap:target,6);memcpy(b+16,ap,6);
   static const uint8_t snap[]={0xaa,0xaa,3,0,0,0,0x88,0x8e};memcpy(b+24,snap,8);uint8_t *e=b+32;e[0]=2;e[1]=3;e[3]=95;e[4]=2;
   unsigned ki=msg==1?0x008a:msg==2?0x010a:msg==3?0x03ca:0x030a;e[5]=ki>>8;e[6]=ki;e[16]=msg<3?1:2;
   if(msg!=4)memset(e+17,msg==2?2:1,32);
   if(msg!=1)memset(e+81,3,16);
   ep->rx_ctrl.sig_len=131;ep->rx_ctrl.dump_len=131;ep->rx_ctrl.channel=2;ep->rx_ctrl.rssi=-40;ep->rx_ctrl.timestamp=esp_timer_get_time();prom_cb(ep,WIFI_PKT_DATA);atomic_fetch_add(&synthetic_eapol,1);
  }
 }
 atomic_store(&synthetic_active,false);drain();control_event="SYNTH_DONE";control(7);atomic_store(&synth_task_running,false);vTaskDelete(NULL);
}
static void configure(bool synth){
 synthetic_only=synth;
 ESP_ERROR_CHECK(nvs_flash_init());ESP_ERROR_CHECK(esp_netif_init());ESP_ERROR_CHECK(esp_event_loop_create_default());
 wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();ESP_ERROR_CHECK(esp_wifi_init(&init));
 ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_NULL));
 ESP_ERROR_CHECK(esp_wifi_set_country_code("CN",false));ESP_ERROR_CHECK(esp_wifi_start());ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
 // Synthetic session deliberately NEVER enables promiscuous RX or CSI capture.
 pool=calloc(DEPTH,sizeof(event_t));configASSERT(pool);free_slots=xQueueCreate(DEPTH,sizeof(event_t*));events=xQueueCreate(DEPTH,sizeof(event_t*));configASSERT(free_slots&&events);
 for(unsigned i=0;i<DEPTH;i++){event_t*e=&pool[i];configASSERT(xQueueSend(free_slots,&e,0)==pdTRUE);}
 if(!synth){
  ESP_ERROR_CHECK(esp_wifi_set_band_mode(channel>14?WIFI_BAND_MODE_5G_ONLY:WIFI_BAND_MODE_2G_ONLY));ESP_ERROR_CHECK(esp_wifi_set_channel(channel,WIFI_SECOND_CHAN_NONE));
  esp_err_t err_c = esp_wifi_get_channel(&actual_chan, &actual_sec);
  esp_err_t err_m = esp_wifi_get_mode(&actual_mode);
  channel_readback_ok = (err_c == ESP_OK && err_m == ESP_OK && actual_chan == channel && actual_mode == WIFI_MODE_NULL);
  wifi_promiscuous_filter_t f={.filter_mask=WIFI_PROMIS_FILTER_MASK_MGMT|WIFI_PROMIS_FILTER_MASK_CTRL|WIFI_PROMIS_FILTER_MASK_DATA|WIFI_PROMIS_FILTER_MASK_MISC};ESP_ERROR_CHECK(esp_wifi_set_promiscuous_filter(&f));ESP_ERROR_CHECK(esp_wifi_set_promiscuous_rx_cb(prom_cb));
  wifi_csi_config_t c={.enable=1,.acquire_csi_legacy=1,.acquire_csi_force_lltf=0,.acquire_csi_ht20=1,.acquire_csi_ht40=1,.acquire_csi_vht=1,.acquire_csi_su=1,.acquire_csi_mu=1,.acquire_csi_dcm=1,.acquire_csi_beamformed=1,.acquire_csi_he_stbc_mode=2,.val_scale_cfg=0,.dump_ack_en=0,.lltf_bit_mode=0};
  ESP_ERROR_CHECK(esp_wifi_set_csi_config(&c));ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_cb,NULL));
 }
 configured=true;configASSERT(xTaskCreate(output_task,"staged_uart",6144,NULL,5,NULL)==pdPASS);control_event="CONFIGURED";control(7);
}
static void change_mode(unsigned mode){
 unsigned old_mode=atomic_load(&capture_mode);
 atomic_store(&capture_mode,MODE_STOP);atomic_store(&synthetic_active,false);
 while(atomic_load(&synth_task_running))vTaskDelay(1);
 if(rf_capture_enabled){ESP_ERROR_CHECK(esp_wifi_set_csi(false));ESP_ERROR_CHECK(esp_wifi_set_promiscuous(false));rf_capture_enabled=false;}
 drain();
 if(old_mode==MODE_HANDSHAKE_DUAL_DIAG&&mode!=MODE_HANDSHAKE_DUAL_DIAG){uint64_t now=esp_timer_get_time();timeline_flush(now,true);dual_stats(now);atomic_store(&dual_capture_active,false);}
 xSemaphoreTakeRecursive(tx_mutex,portMAX_DELAY);atomic_fetch_add(&mode_epoch,1);
 if(mode==MODE_HANDSHAKE_DUAL_DIAG){dual_reset(esp_timer_get_time());atomic_store(&dual_capture_active,true);}
 atomic_store(&capture_mode,mode);
 if(mode!=MODE_STOP&&!synthetic_only){ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));ESP_ERROR_CHECK(esp_wifi_set_csi(true));rf_capture_enabled=true;}
 control_event="MODE_ACK";control(7); // ACK only after setup; prior mode drained, counters cumulative.
 xSemaphoreGiveRecursive(tx_mutex);
 if(mode==MODE_STOP){control(FINAL);uart_wait_tx_done(UART_NUM_0,pdMS_TO_TICKS(5000));}
}
void app_main(void){
 esp_log_level_set("*",ESP_LOG_NONE);setvbuf(stdout,NULL,_IONBF,0);
 ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0,2048,16384,0,NULL,0));esp_vfs_dev_uart_use_driver(UART_NUM_0);tx_mutex=xSemaphoreCreateRecursiveMutex();configASSERT(tx_mutex);
 uint32_t actual;ESP_ERROR_CHECK(uart_get_baudrate(UART_NUM_0,&actual));
 wifi_pkt_rx_ctrl_t sm={0},dm={0};sm.sig_len=0x3fff;dm.dump_len=0x3fff;
  printf("{\"event\":\"READY\",\"version\":\"sniffer-8d-csi-centric\",\"baud\":%u,\"rx_ctrl_size\":%u,\"candidate_max\":%u,\"sig_first_byte\":%u,\"dump_first_byte\":%u,\"mac_version\":%u,\"rf_capture_enabled\":false}\n",(unsigned)actual,(unsigned)sizeof(wifi_pkt_rx_ctrl_t),CANDIDATE_MAX,first_set(&sm),first_set(&dm),CONFIG_SOC_WIFI_MAC_VERSION_NUM);
 char line[180];unsigned baud,ch,m[6],a[6],rate,seconds;
 for(;;){
  if(!fgets(line,sizeof(line),stdin)){vTaskDelay(1);continue;}
  line[strcspn(line,"\r\n")]=0;
  if(!configured&&sscanf(line,"SET_BAUD %u",&baud)==1&&(baud==3000000||baud==2500000||baud==2000000||baud==921600)){
   printf("{\"event\":\"BAUD_ACK\",\"requested\":%u}\n",baud);uart_wait_tx_done(UART_NUM_0,pdMS_TO_TICKS(2000));vTaskDelay(pdMS_TO_TICKS(150));ESP_ERROR_CHECK(uart_set_baudrate(UART_NUM_0,baud));ESP_ERROR_CHECK(uart_get_baudrate(UART_NUM_0,&actual));printf("{\"event\":\"BAUD_READY\",\"requested\":%u,\"actual\":%u}\n",baud,(unsigned)actual);
  }else if(!configured&&!strcmp(line,"CFG,SYNTH")){
   channel=2;target[0]=ap[0]=2;target[5]=1;ap[5]=2;configure(true);
  }else if(!configured&&sscanf(line,"CFG,%u,%x:%x:%x:%x:%x:%x,%x:%x:%x:%x:%x:%x",&ch,&m[0],&m[1],&m[2],&m[3],&m[4],&m[5],&a[0],&a[1],&a[2],&a[3],&a[4],&a[5])==13&&ch>0&&ch<200){
   bool ok=true;for(unsigned i=0;i<6;i++)if(m[i]>255||a[i]>255)ok=false;
   if(ok){channel=ch;for(unsigned i=0;i<6;i++){target[i]=m[i];ap[i]=a[i];}configure(false);}
  }else if(configured&&(!strcmp(line,"MODE HANDSHAKE")||!strcmp(line,"MODE HANDSHAKE_DIAG")||!strcmp(line,"MODE HANDSHAKE_DUAL_DIAG")||!strcmp(line,"MODE PROBE")||!strcmp(line,"MODE STOP"))){
   if(atomic_load(&synthetic_active)&&strcmp(line,"MODE STOP")){control_event="BUSY";control(7);continue;}
    change_mode(!strcmp(line,"MODE HANDSHAKE")?MODE_HANDSHAKE:!strcmp(line,"MODE HANDSHAKE_DIAG")?MODE_HANDSHAKE_DIAG:!strcmp(line,"MODE HANDSHAKE_DUAL_DIAG")?MODE_HANDSHAKE_DUAL_DIAG:!strcmp(line,"MODE PROBE")?MODE_PROBE:MODE_STOP);
  }else if(configured&&synthetic_only&&!atomic_load(&synthetic_active)&&atomic_load(&capture_mode)!=MODE_STOP&&sscanf(line,"SYNTH %u %u",&rate,&seconds)==2&&rate>0&&rate<=200&&seconds>0&&seconds<=30){
   synth_rate=rate;synth_seconds=seconds;atomic_store(&synthetic_active,true);atomic_store(&synth_task_running,true);control_event="SYNTH_ACK";control(7);configASSERT(xTaskCreate(synth_task,"synthetic_callbacks",6144,NULL,6,NULL)==pdPASS);
  }else if(configured){control_event="ERROR";control(7);}
  else printf("{\"event\":\"ERROR\"}\n");
 }
}
