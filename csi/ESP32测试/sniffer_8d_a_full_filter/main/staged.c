// Real RF path and explicitly marked synthetic engineering path share callbacks.
#include "capture_core.inc"
static atomic_bool synth_task_running;
static void open_ap_wifi_event(void *arg,esp_event_base_t base,int32_t id,void *data){
 (void)arg;
 if(base!=WIFI_EVENT)return;
 if(id==WIFI_EVENT_AP_STACONNECTED){
  wifi_event_ap_staconnected_t *event=(wifi_event_ap_staconnected_t*)data;
  memcpy(target,event->mac,6);atomic_store(&open_ap_station_connected,true);
  open_ap_stats_control("AP_STA_CONNECTED");
 }else if(id==WIFI_EVENT_AP_STADISCONNECTED){
  wifi_event_ap_stadisconnected_t *event=(wifi_event_ap_stadisconnected_t*)data;
  if(same(target,event->mac)){memset(target,0,sizeof(target));atomic_store(&open_ap_station_connected,false);}
  open_ap_stats_control("AP_STA_DISCONNECTED");
 }
}
static void open_ap_init_status_detail(const char *api,esp_err_t err,unsigned detail_code){
 static event_t e;memset(e.header,0,HDR);
 memcpy(e.header,"CS8R",4);e.header[4]=1;e.header[5]=7;put16(e.header+6,HDR);
 const char *event_name=err==ESP_OK?"OPEN_AP_INIT":"OPEN_AP_INIT_FAILED";
 int n=snprintf((char*)e.data,CAP,
  "{\"event\":\"%s\",\"api\":\"%s\",\"ok\":%s,\"err\":%d,\"err_name\":\"%s\",\"detail_code\":%u}",
  event_name,api,err==ESP_OK?"true":"false",(int)err,esp_err_to_name(err),detail_code);
 if(n>0&&n<CAP){put16(e.header+34,n);put16(e.header+36,n);put64(e.header+16,esp_timer_get_time());emit(&e);}
}
static void open_ap_init_status(const char *api,esp_err_t err){open_ap_init_status_detail(api,err,0);}
static int decode_probe_datagram(const uint8_t *p,int n,uint32_t *run_id,uint32_t *packet_id,uint64_t *sender_ns){
 if(n!=UDP_PROBE_PACKET_LEN||memcmp(p,"CSID",4)!=0)return -2;
 if(p[4]!=1||p[5]!=28||le16(p+6)!=0||le16(p+24)!=16||le16(p+26)!=0)return -2;
 *run_id=get32(p+8);*packet_id=get32(p+12);*sender_ns=get64(p+16);
 if(get32(p+44)!=crc32(p,44))return -1;
 for(unsigned i=0;i<16;i++)if(p[28+i]!=(uint8_t)(*packet_id+i))return 0;
 return 1;
}
static void udp_receiver_task(void *arg){
 (void)arg;atomic_store(&udp_server_task_running,true);int fd=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
 if(fd<0){atomic_store(&udp_server_error,(unsigned)errno);atomic_store(&udp_server_ready,false);atomic_store(&udp_server_task_running,false);vTaskDelete(NULL);return;}
 struct timeval timeout={.tv_sec=0,.tv_usec=500000};
 (void)setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));
 struct sockaddr_in addr={0};addr.sin_family=AF_INET;addr.sin_port=htons(UDP_PROBE_PORT);addr.sin_addr.s_addr=htonl(INADDR_ANY);
 if(bind(fd,(struct sockaddr*)&addr,sizeof(addr))<0){atomic_store(&udp_server_error,(unsigned)errno);atomic_store(&udp_server_ready,false);close(fd);atomic_store(&udp_server_task_running,false);vTaskDelete(NULL);return;}
 atomic_store(&udp_server_ready,true);uint8_t packet[512];
 while(!atomic_load(&udp_server_stop)){
  struct sockaddr_in peer;socklen_t peer_len=sizeof(peer);
  int n=recvfrom(fd,packet,sizeof(packet),0,(struct sockaddr*)&peer,&peer_len);
  if(n<0){if(errno==EAGAIN||errno==EWOULDBLOCK||errno==EINTR)continue;atomic_store(&udp_server_error,(unsigned)errno);vTaskDelay(pdMS_TO_TICKS(100));continue;}
  if(!atomic_load(&udp_server_active)||atomic_load(&capture_mode)!=MODE_OPEN_AP_POC)continue;
  atomic_fetch_add(&udp_rx_total,1);uint32_t run_id=0,packet_id=0;uint64_t sender_ns=0;
  int verdict=decode_probe_datagram(packet,n,&run_id,&packet_id,&sender_ns);bool valid=verdict==1,crc_ok=verdict>=0,duplicate=false;
  if(verdict==-1)atomic_fetch_add(&udp_crc_fail,1);
  if(crc_ok)atomic_fetch_add(&udp_crc_ok,1);
  if(verdict==1){
   atomic_fetch_add(&udp_valid,1);
   for(unsigned i=0;i<udp_seen_count;i++)if(udp_seen[i].run_id==run_id&&udp_seen[i].packet_id==packet_id){duplicate=true;break;}
   if(duplicate)atomic_fetch_add(&udp_duplicate,1);
   else{if(udp_seen_count<UDP_PROBE_SEEN_CAP){udp_seen[udp_seen_count].run_id=run_id;udp_seen[udp_seen_count].packet_id=packet_id;udp_seen_count++;}atomic_fetch_add(&udp_unique,1);}
  }else atomic_fetch_add(&udp_invalid,1);
  open_ap_udp_rx_control(run_id,packet_id,sender_ns,(uint64_t)esp_timer_get_time(),valid,crc_ok,duplicate,(unsigned)n);
 }
 atomic_store(&udp_server_ready,false);close(fd);atomic_store(&udp_server_task_running,false);vTaskDelete(NULL);
}
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
static bool configure_open_ap(void){
 const char *failed_api="open_ap_setup";esp_err_t failed_err=ESP_FAIL;
 bool wifi_started=false,promisc_started=false,udp_task_started=false;
 wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();wifi_config_t cfg={0};
 wifi_csi_config_t csi={.enable=1,.acquire_csi_legacy=1,.acquire_csi_force_lltf=0,
  .acquire_csi_ht20=1,.acquire_csi_ht40=1,.acquire_csi_vht=1,.acquire_csi_su=1,
  .acquire_csi_mu=1,.acquire_csi_dcm=1,.acquire_csi_beamformed=1,
  .acquire_csi_he_stbc_mode=2,.val_scale_cfg=0,.dump_ack_en=0,.lltf_bit_mode=0};
#define OPEN_AP_TRY(api_name,expression) do{failed_api=(api_name);failed_err=(expression);open_ap_init_status(failed_api,failed_err);if(failed_err!=ESP_OK)goto fail;}while(0)
 synthetic_only=false;open_ap_setup_failed=false;configured=false;
 atomic_store(&capture_mode,MODE_STOP);atomic_store(&rf_capture_enabled,false);
 atomic_store(&udp_server_active,false);atomic_store(&udp_server_stop,false);
 atomic_store(&udp_server_ready,false);atomic_store(&udp_server_error,0);atomic_store(&udp_server_task_running,false);
 channel_readback_ok=false;open_ap_bandwidth_mhz=0;actual_chan=0;actual_sec=WIFI_SECOND_CHAN_NONE;actual_mode=WIFI_MODE_NULL;
 OPEN_AP_TRY("nvs_flash_init",nvs_flash_init());
 OPEN_AP_TRY("esp_netif_init",esp_netif_init());
 OPEN_AP_TRY("esp_event_loop_create_default",esp_event_loop_create_default());
 open_ap_netif=esp_netif_create_default_wifi_ap();
 failed_api="esp_netif_create_default_wifi_ap";failed_err=open_ap_netif?ESP_OK:ESP_ERR_NO_MEM;
 open_ap_init_status(failed_api,failed_err);if(failed_err!=ESP_OK)goto fail;
 OPEN_AP_TRY("esp_wifi_init",esp_wifi_init(&init));
 OPEN_AP_TRY("esp_wifi_set_storage",esp_wifi_set_storage(WIFI_STORAGE_RAM));
 OPEN_AP_TRY("esp_wifi_set_country_code",esp_wifi_set_country_code("CN",false));
 OPEN_AP_TRY("esp_event_handler_register",esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,open_ap_wifi_event,NULL));
 OPEN_AP_TRY("esp_wifi_set_mode",esp_wifi_set_mode(WIFI_MODE_AP));
 size_t ssid_len=strlen(open_ap_ssid);memcpy(cfg.ap.ssid,open_ap_ssid,ssid_len);cfg.ap.ssid_len=ssid_len;
 cfg.ap.channel=(uint8_t)channel;cfg.ap.authmode=WIFI_AUTH_OPEN;cfg.ap.max_connection=1;cfg.ap.ssid_hidden=0;cfg.ap.beacon_interval=100;
 OPEN_AP_TRY("esp_wifi_set_config",esp_wifi_set_config(WIFI_IF_AP,&cfg));
 OPEN_AP_TRY("esp_wifi_start",esp_wifi_start());wifi_started=true;
 // IDF 5.5.5 requires the driver to be started before changing its band mode.
 OPEN_AP_TRY("esp_wifi_set_band_mode",esp_wifi_set_band_mode(WIFI_BAND_MODE_2G_ONLY));
 OPEN_AP_TRY("esp_wifi_set_channel",esp_wifi_set_channel((uint8_t)channel,WIFI_SECOND_CHAN_NONE));
 OPEN_AP_TRY("esp_wifi_set_bandwidth",esp_wifi_set_bandwidth(WIFI_IF_AP,WIFI_BW_HT20));
 OPEN_AP_TRY("esp_wifi_set_ps",esp_wifi_set_ps(WIFI_PS_NONE));
 OPEN_AP_TRY("esp_wifi_get_mac",esp_wifi_get_mac(WIFI_IF_AP,ap));
 wifi_bandwidth_t bw=WIFI_BW20;
 OPEN_AP_TRY("esp_wifi_get_bandwidth",esp_wifi_get_bandwidth(WIFI_IF_AP,&bw));
 open_ap_bandwidth_mhz=bw==WIFI_BW_HT20?20:bw==WIFI_BW_HT40?40:0;
 OPEN_AP_TRY("esp_wifi_get_channel",esp_wifi_get_channel(&actual_chan,&actual_sec));
 OPEN_AP_TRY("esp_wifi_get_mode",esp_wifi_get_mode(&actual_mode));
 channel_readback_ok=actual_chan==channel&&actual_mode==WIFI_MODE_AP&&open_ap_bandwidth_mhz==20;
 if(!channel_readback_ok){failed_api="softap_channel_bandwidth_readback";failed_err=ESP_FAIL;open_ap_init_status(failed_api,failed_err);goto fail;}
 esp_netif_ip_info_t ip_info={0};
 OPEN_AP_TRY("esp_netif_get_ip_info",esp_netif_get_ip_info(open_ap_netif,&ip_info));
 snprintf(open_ap_ip,sizeof(open_ap_ip),IPSTR,IP2STR(&ip_info.ip));
 // IDF 5.5.5 CSI config/enable requires started Wi-Fi and promiscuous RX.
 OPEN_AP_TRY("esp_wifi_set_promiscuous(true)",esp_wifi_set_promiscuous(true));promisc_started=true;promisc_capture_enabled=true;
 OPEN_AP_TRY("esp_wifi_set_csi_config",esp_wifi_set_csi_config(&csi));
 OPEN_AP_TRY("esp_wifi_set_csi_rx_cb",esp_wifi_set_csi_rx_cb(csi_cb,NULL));

 pool=calloc(DEPTH,sizeof(event_t));free_slots=xQueueCreate(DEPTH,sizeof(event_t*));events=xQueueCreate(DEPTH,sizeof(event_t*));
 if(!pool||!free_slots||!events){failed_api="capture_queue_allocation";failed_err=ESP_ERR_NO_MEM;open_ap_init_status(failed_api,failed_err);goto fail;}
 for(unsigned i=0;i<DEPTH;i++){event_t *e=&pool[i];if(xQueueSend(free_slots,&e,0)!=pdTRUE){failed_api="capture_queue_seed";failed_err=ESP_FAIL;open_ap_init_status(failed_api,failed_err);goto fail;}}
 atomic_store(&udp_server_stop,false);atomic_store(&udp_server_task_running,true);
 BaseType_t task_ok=xTaskCreate(udp_receiver_task,"open_ap_udp",4096,NULL,5,NULL);
 if(task_ok!=pdPASS)atomic_store(&udp_server_task_running,false);
 failed_api="udp_receiver_task_start";failed_err=task_ok==pdPASS?ESP_OK:ESP_ERR_NO_MEM;open_ap_init_status(failed_api,failed_err);
 if(failed_err!=ESP_OK)goto fail;
 udp_task_started=true;
 for(unsigned i=0;i<25&&!atomic_load(&udp_server_ready)&&!U(udp_server_error);i++)vTaskDelay(pdMS_TO_TICKS(100));
 if(!atomic_load(&udp_server_ready)){
  unsigned system_error=U(udp_server_error);failed_api="udp_server_bind";failed_err=ESP_FAIL;
  open_ap_init_status_detail(failed_api,failed_err,system_error);goto fail;
 }
 open_ap_init_status("udp_server_bind",ESP_OK);
 OPEN_AP_TRY("xTaskCreate(output_task)",xTaskCreate(output_task,"staged_uart",6144,NULL,5,NULL)==pdPASS?ESP_OK:ESP_ERR_NO_MEM);
 configured=true;open_ap_stats_control("OPEN_AP_READY");
#undef OPEN_AP_TRY
 return true;
fail:
 atomic_store(&udp_server_active,false);atomic_store(&udp_server_stop,true);atomic_store(&capture_mode,MODE_STOP);
 atomic_store(&rf_capture_enabled,false);configured=false;
 if(udp_task_started)for(unsigned i=0;i<10&&atomic_load(&udp_server_task_running);i++)vTaskDelay(pdMS_TO_TICKS(100));
 atomic_store(&udp_server_ready,false);
 if(promisc_started){esp_err_t e=esp_wifi_set_promiscuous(false);open_ap_init_status("cleanup_esp_wifi_set_promiscuous(false)",e);promisc_capture_enabled=false;}
 if(wifi_started){esp_err_t e=esp_wifi_stop();open_ap_init_status("cleanup_esp_wifi_stop",e);}
 if(events){vQueueDelete(events);events=NULL;}if(free_slots){vQueueDelete(free_slots);free_slots=NULL;}free(pool);pool=NULL;
 open_ap_setup_failed=true;
 (void)failed_api;(void)failed_err;
#undef OPEN_AP_TRY
 return false;
}
static void configure(bool synth){
 if(open_ap_configured){(void)configure_open_ap();return;}
 synthetic_only=synth;
 ESP_ERROR_CHECK(nvs_flash_init());ESP_ERROR_CHECK(esp_netif_init());ESP_ERROR_CHECK(esp_event_loop_create_default());
 wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();ESP_ERROR_CHECK(esp_wifi_init(&init));
 ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));ESP_ERROR_CHECK(esp_wifi_set_country_code("CN",false));
 ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_NULL));ESP_ERROR_CHECK(esp_wifi_start());ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
 // Synthetic session deliberately NEVER enables promiscuous RX or CSI capture.
 pool=calloc(DEPTH,sizeof(event_t));configASSERT(pool);free_slots=xQueueCreate(DEPTH,sizeof(event_t*));events=xQueueCreate(DEPTH,sizeof(event_t*));configASSERT(free_slots&&events);
 for(unsigned i=0;i<DEPTH;i++){event_t*e=&pool[i];configASSERT(xQueueSend(free_slots,&e,0)==pdTRUE);}
 if(!synth){
  ESP_ERROR_CHECK(esp_wifi_set_band_mode(channel>14?WIFI_BAND_MODE_5G_ONLY:WIFI_BAND_MODE_2G_ONLY));ESP_ERROR_CHECK(esp_wifi_set_channel(channel,WIFI_SECOND_CHAN_NONE));
  esp_err_t err_c=esp_wifi_get_channel(&actual_chan,&actual_sec);esp_err_t err_m=esp_wifi_get_mode(&actual_mode);
  channel_readback_ok=(err_c==ESP_OK&&err_m==ESP_OK&&actual_chan==channel&&actual_mode==WIFI_MODE_NULL);
  wifi_promiscuous_filter_t f={.filter_mask=WIFI_PROMIS_FILTER_MASK_MGMT|WIFI_PROMIS_FILTER_MASK_CTRL|WIFI_PROMIS_FILTER_MASK_DATA|WIFI_PROMIS_FILTER_MASK_MISC};ESP_ERROR_CHECK(esp_wifi_set_promiscuous_filter(&f));ESP_ERROR_CHECK(esp_wifi_set_promiscuous_rx_cb(prom_cb));
  wifi_csi_config_t c={.enable=1,.acquire_csi_legacy=1,.acquire_csi_force_lltf=0,.acquire_csi_ht20=1,.acquire_csi_ht40=1,.acquire_csi_vht=1,.acquire_csi_su=1,.acquire_csi_mu=1,.acquire_csi_dcm=1,.acquire_csi_beamformed=1,.acquire_csi_he_stbc_mode=2,.val_scale_cfg=0,.dump_ack_en=0,.lltf_bit_mode=0};
  ESP_ERROR_CHECK(esp_wifi_set_csi_config(&c));ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_cb,NULL));
 }
 configured=true;configASSERT(xTaskCreate(output_task,"staged_uart",6144,NULL,5,NULL)==pdPASS);
 control_event="CONFIGURED";control(7);
}
static void change_mode(unsigned mode){
 unsigned old_mode=atomic_load(&capture_mode);bool open_ap_stop_ok=true;
 atomic_store(&capture_mode,MODE_STOP);atomic_store(&synthetic_active,false);
 if(open_ap_configured)atomic_store(&udp_server_active,false);
 while(atomic_load(&synth_task_running))vTaskDelay(1);
 if(rf_capture_enabled){
  esp_err_t csi_err=esp_wifi_set_csi(false);
  if(open_ap_configured){open_ap_init_status("esp_wifi_set_csi(false)",csi_err);if(csi_err!=ESP_OK){open_ap_setup_failed=true;open_ap_stop_ok=false;}}
  else ESP_ERROR_CHECK(csi_err);
  if(promisc_capture_enabled&&!open_ap_configured){ESP_ERROR_CHECK(esp_wifi_set_promiscuous(false));promisc_capture_enabled=false;}
  rf_capture_enabled=false;
 }
 drain();
 if(old_mode==MODE_HANDSHAKE_DUAL_DIAG&&mode!=MODE_HANDSHAKE_DUAL_DIAG){uint64_t now=esp_timer_get_time();timeline_flush(now,true);dual_stats(now);atomic_store(&dual_capture_active,false);}
 if(open_ap_configured&&old_mode==MODE_OPEN_AP_POC&&mode==MODE_STOP)open_ap_stats_control("OPEN_AP_FINAL_STATS");
 xSemaphoreTakeRecursive(tx_mutex,portMAX_DELAY);atomic_fetch_add(&mode_epoch,1);
 if(mode==MODE_HANDSHAKE_DUAL_DIAG){dual_reset(esp_timer_get_time());atomic_store(&dual_capture_active,true);}
 if(!open_ap_stop_ok){control_event="OPEN_AP_INIT_FAILED";control(7);xSemaphoreGiveRecursive(tx_mutex);return;}
 if(open_ap_configured&&mode!=MODE_STOP){
  if(mode!=MODE_OPEN_AP_POC){atomic_store(&capture_mode,MODE_STOP);control_event="OPEN_AP_MODE_REQUIRED";control(7);xSemaphoreGiveRecursive(tx_mutex);return;}
  atomic_store(&open_pair_csi,0);atomic_store(&open_uplink_csi,0);atomic_store(&open_downlink_csi,0);
  atomic_store(&open_data_frame,0);atomic_store(&open_qos_data,0);atomic_store(&open_non_qos_data,0);
  atomic_store(&open_clear_data,0);atomic_store(&open_protected_data,0);atomic_store(&open_csi_data_enqueued,0);atomic_store(&open_csi_data_output,0);
  atomic_store(&open_csid_magic_seen,0);atomic_store(&open_csid_packet_id_parsed,0);
  atomic_store(&udp_rx_total,0);atomic_store(&udp_valid,0);atomic_store(&udp_crc_ok,0);atomic_store(&udp_crc_fail,0);atomic_store(&udp_invalid,0);atomic_store(&udp_duplicate,0);atomic_store(&udp_unique,0);udp_seen_count=0;
  atomic_store(&capture_mode,MODE_OPEN_AP_POC);
  esp_err_t csi_err=esp_wifi_set_csi(true);open_ap_init_status("esp_wifi_set_csi(true)",csi_err);
  if(csi_err!=ESP_OK){atomic_store(&capture_mode,MODE_STOP);atomic_store(&udp_server_active,false);rf_capture_enabled=false;open_ap_setup_failed=true;xSemaphoreGiveRecursive(tx_mutex);return;}
  rf_capture_enabled=true;atomic_store(&udp_server_active,true);
 }else if(mode!=MODE_STOP&&!synthetic_only){
  atomic_store(&capture_mode,mode);ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));promisc_capture_enabled=true;
  ESP_ERROR_CHECK(esp_wifi_set_csi(true));rf_capture_enabled=true;
 }else{
  atomic_store(&capture_mode,mode);
  if(mode==MODE_STOP)atomic_store(&udp_server_active,false);
 }
 control_event="MODE_ACK";control(7); // ACK only after setup; prior mode drained, counters cumulative.
 xSemaphoreGiveRecursive(tx_mutex);
 if(mode==MODE_STOP){control(FINAL);uart_wait_tx_done(UART_NUM_0,pdMS_TO_TICKS(5000));}
}
void app_main(void){
 esp_log_level_set("*",ESP_LOG_NONE);setvbuf(stdout,NULL,_IONBF,0);
 ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0,2048,16384,0,NULL,0));esp_vfs_dev_uart_use_driver(UART_NUM_0);tx_mutex=xSemaphoreCreateRecursiveMutex();configASSERT(tx_mutex);
 uint32_t actual;ESP_ERROR_CHECK(uart_get_baudrate(UART_NUM_0,&actual));
 wifi_pkt_rx_ctrl_t sm={0},dm={0};sm.sig_len=0x3fff;dm.dump_len=0x3fff;
  printf("{\"event\":\"READY\",\"version\":\"sniffer-8d-csi-centric\",\"open_ap_poc\":true,\"baud\":%u,\"rx_ctrl_size\":%u,\"candidate_max\":%u,\"sig_first_byte\":%u,\"dump_first_byte\":%u,\"mac_version\":%u,\"rf_capture_enabled\":false}\n",(unsigned)actual,(unsigned)sizeof(wifi_pkt_rx_ctrl_t),CANDIDATE_MAX,first_set(&sm),first_set(&dm),CONFIG_SOC_WIFI_MAC_VERSION_NUM);
 char line[180];unsigned baud,ch,m[6],a[6],rate,seconds;
 for(;;){
  if(!fgets(line,sizeof(line),stdin)){vTaskDelay(1);continue;}
  line[strcspn(line,"\r\n")]=0;
  if(open_ap_setup_failed){
   if(!strncmp(line,"CFG_OPEN_AP,",11)||!strncmp(line,"MODE ",5))open_ap_init_status("open_ap_setup_latched",ESP_FAIL);
   continue;
  }
  if(!configured&&sscanf(line,"SET_BAUD %u",&baud)==1&&(baud==3000000||baud==2500000||baud==2000000||baud==921600)){
   printf("{\"event\":\"BAUD_ACK\",\"requested\":%u}\n",baud);uart_wait_tx_done(UART_NUM_0,pdMS_TO_TICKS(2000));vTaskDelay(pdMS_TO_TICKS(150));ESP_ERROR_CHECK(uart_set_baudrate(UART_NUM_0,baud));ESP_ERROR_CHECK(uart_get_baudrate(UART_NUM_0,&actual));printf("{\"event\":\"BAUD_READY\",\"requested\":%u,\"actual\":%u}\n",baud,(unsigned)actual);
  }else if(!configured&&!strcmp(line,"CFG,SYNTH")){
   channel=2;target[0]=ap[0]=2;target[5]=1;ap[5]=2;configure(true);
  }else if(!configured&&sscanf(line,"CFG_OPEN_AP,%u,%32[^,\r\n]",&ch,open_ap_ssid)==2&&ch==2&&open_ap_ssid[0]){
   channel=ch;open_ap_configured=true;configure(false);
  }else if(!configured&&sscanf(line,"CFG,%u,%x:%x:%x:%x:%x:%x,%x:%x:%x:%x:%x:%x",&ch,&m[0],&m[1],&m[2],&m[3],&m[4],&m[5],&a[0],&a[1],&a[2],&a[3],&a[4],&a[5])==13&&ch>0&&ch<200){
   bool ok=true;for(unsigned i=0;i<6;i++)if(m[i]>255||a[i]>255)ok=false;
   if(ok){channel=ch;for(unsigned i=0;i<6;i++){target[i]=m[i];ap[i]=a[i];}configure(false);}
  }else if(configured&&(!strcmp(line,"MODE HANDSHAKE")||!strcmp(line,"MODE HANDSHAKE_DIAG")||!strcmp(line,"MODE HANDSHAKE_DUAL_DIAG")||!strcmp(line,"MODE PROBE")||!strcmp(line,"MODE OPEN_AP_POC")||!strcmp(line,"MODE STOP"))){
   if(atomic_load(&synthetic_active)&&strcmp(line,"MODE STOP")){control_event="BUSY";control(7);continue;}
    change_mode(!strcmp(line,"MODE HANDSHAKE")?MODE_HANDSHAKE:!strcmp(line,"MODE HANDSHAKE_DIAG")?MODE_HANDSHAKE_DIAG:!strcmp(line,"MODE HANDSHAKE_DUAL_DIAG")?MODE_HANDSHAKE_DUAL_DIAG:!strcmp(line,"MODE PROBE")?MODE_PROBE:!strcmp(line,"MODE OPEN_AP_POC")?MODE_OPEN_AP_POC:MODE_STOP);
  }else if(configured&&synthetic_only&&!atomic_load(&synthetic_active)&&atomic_load(&capture_mode)!=MODE_STOP&&sscanf(line,"SYNTH %u %u",&rate,&seconds)==2&&rate>0&&rate<=200&&seconds>0&&seconds<=30){
   synth_rate=rate;synth_seconds=seconds;atomic_store(&synthetic_active,true);atomic_store(&synth_task_running,true);control_event="SYNTH_ACK";control(7);configASSERT(xTaskCreate(synth_task,"synthetic_callbacks",6144,NULL,6,NULL)==pdPASS);
  }else if(configured){control_event="ERROR";control(7);}
  else printf("{\"event\":\"ERROR\"}\n");
 }
}
