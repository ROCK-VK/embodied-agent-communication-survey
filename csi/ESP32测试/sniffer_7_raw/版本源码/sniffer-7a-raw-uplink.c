// Gate A: target uplink Data + pair EAPOL only; no ordinary downlink raw export.
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdatomic.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_wifi.h"
#include "esp_mac.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "nvs_flash.h"
#include "driver/uart.h"
#include "esp_vfs_dev.h"

#define CAP 4096
#define CSI_CAP 2048
#define DEPTH 24
#define HDR 62
#define RAW 1
#define CSI 2
#define STATS 3
#define ARMED 4
#define FINAL 5
#define FCS_ABSENT 1
#define TRUNCATED 2
#define EAPOL 4
#define UPLINK 8
typedef struct { uint8_t header[HDR]; uint8_t data[CAP]; } event_t;
static event_t pool[DEPTH];
static QueueHandle_t free_slots, events;
static uint8_t target[6], ap[6];
static unsigned channel, serial_id;
static atomic_bool running;
static atomic_uint prom_total, pair_frames, eapol_frames, csi_total, target_csi;
static atomic_uint prom_data_all, prom_mgmt_all, prom_ctrl_all, prom_misc_all;
static atomic_uint pair_seen, uplink_data_cb, downlink_eapol_cb, csi_source_cb;
static atomic_uint raw_drop, csi_drop, raw_enqueued, csi_enqueued, raw_output, csi_output;
static atomic_uint raw_truncated, csi_truncated, csi_empty, hdr_conflict, high_water, write_errors, wire_bytes;
static uint16_t le16(const uint8_t *p) { return p[0] | (p[1]<<8); }
static void put16(uint8_t *p, unsigned v) { p[0]=v; p[1]=v>>8; }
static void put32(uint8_t *p, uint32_t v) { for(unsigned i=0;i<4;i++) p[i]=v>>(8*i); }
static void put64(uint8_t *p, uint64_t v) { for(unsigned i=0;i<8;i++) p[i]=v>>(8*i); }
static bool same(const uint8_t *a,const uint8_t *b) { return memcmp(a,b,6)==0; }
static unsigned header_length(const uint8_t *p, unsigned n) {
    if(n<24) return 0;
    uint16_t fc=le16(p); if(((fc>>2)&3)!=2) return 0;
    unsigned h=24;
    if((fc&0x300)==0x300) h+=6;
    if(fc&0x80) { h+=2; if(fc&0x8000) h+=4; }
    return n>=h?h:0;
}
static bool is_eapol(const uint8_t *p,unsigned n,unsigned h) {
    static const uint8_t llc[]={0xaa,0xaa,3,0,0,0,0x88,0x8e};
    // Protected/A-MSDU/fragmented bodies are not guessed to be LLC; raw still retained.
    uint16_t fc=le16(p);
    if(fc&0x4000 || fc&0x400 || (le16(p+22)&15)) return false;
    unsigned qos=24+(((fc&0x300)==0x300)?6:0);
    if((fc&0x80) && (p[qos]&0x80)) return false;
    return n>=h+8 && memcmp(p+h,llc,8)==0;
}
static event_t *take(void) {
    event_t *e=NULL; if(xQueueReceive(free_slots,&e,0)!=pdTRUE) return NULL;
    memset(e->header,0,HDR); return e;
}
static void common(event_t *e,unsigned kind,const wifi_pkt_rx_ctrl_t *m,const uint8_t *h) {
    uint8_t *p=e->header;memcpy(p,"CS7R",4);p[4]=1;p[5]=kind;put16(p+6,HDR);
    put32(p+12,m->timestamp);put64(p+16,esp_timer_get_time());
    put16(p+24,le16(h));put16(p+26,le16(h+22));p[28]=m->channel;
    p[29]=m->cur_bb_format;p[30]=(uint8_t)m->rssi;p[31]=m->rx_state;
    put16(p+38,m->sig_len);memcpy(p+40,h+10,6);memcpy(p+46,h+4,6);
}
static void enqueue(event_t *e) {
    // A free pool slot guarantees room in the equally sized pointer queue.
    unsigned kind=e->header[5];
    configASSERT(xQueueSend(events,&e,0)==pdTRUE);
    if(kind==RAW) atomic_fetch_add(&raw_enqueued,1);else atomic_fetch_add(&csi_enqueued,1);
    unsigned n=uxQueueMessagesWaiting(events),old=atomic_load(&high_water);
    while(n>old && !atomic_compare_exchange_weak(&high_water,&old,n)) {}
}
static void prom_cb(void *buf,wifi_promiscuous_pkt_type_t kind) {
    atomic_fetch_add(&prom_total,1);
    if(kind==WIFI_PKT_DATA)atomic_fetch_add(&prom_data_all,1);
    else if(kind==WIFI_PKT_MGMT)atomic_fetch_add(&prom_mgmt_all,1);
    else if(kind==WIFI_PKT_CTRL)atomic_fetch_add(&prom_ctrl_all,1);
    else atomic_fetch_add(&prom_misc_all,1);
    if(!buf || kind!=WIFI_PKT_DATA) return; // Others count only, never dereference misc.
    const wifi_promiscuous_pkt_t *p=buf;unsigned n=p->rx_ctrl.dump_len;
    unsigned h=header_length(p->payload,n);if(!h) return;
    bool up=same(p->payload+10,target)&&same(p->payload+4,ap);
    bool down=same(p->payload+10,ap)&&same(p->payload+4,target);
    if(!up&&!down) return;
    atomic_fetch_add(&pair_seen,1);
    bool ep=is_eapol(p->payload,n,h);
    if(!up && !ep)return; // Only uplink Data or positively identified pair EAPOL.
    atomic_fetch_add(&pair_frames,1);
    if(up)atomic_fetch_add(&uplink_data_cb,1);else atomic_fetch_add(&downlink_eapol_cb,1);
    if(ep)atomic_fetch_add(&eapol_frames,1);
    event_t *e=take();if(!e){atomic_fetch_add(&raw_drop,1);return;}
    common(e,RAW,&p->rx_ctrl,p->payload);
    unsigned copy=n>CAP?CAP:n;
    put16(e->header+32,FCS_ABSENT|(n>CAP?TRUNCATED:0)|(ep?EAPOL:0)|(up?UPLINK:0));
    put16(e->header+34,n);put16(e->header+36,copy);
    if(n>CAP)atomic_fetch_add(&raw_truncated,1);
    // IDF5.5.5 C5 dump_len explicitly excludes FCS. Never read sig_len bytes here.
    memcpy(e->data,p->payload,copy);enqueue(e);
}
static void csi_cb(void *ctx,wifi_csi_info_t *p) {
    (void)ctx;atomic_fetch_add(&csi_total,1);
    if(!p){atomic_fetch_add(&csi_empty,1);return;}
    if(!same(p->mac,target))return;
    atomic_fetch_add(&csi_source_cb,1);
    if(!p->buf||!p->len){atomic_fetch_add(&csi_empty,1);return;}
    if(!p->hdr || p->rx_ctrl.dump_len<24 || !header_length(p->hdr,p->rx_ctrl.dump_len))return;
    if(!same(p->hdr+10,target)){atomic_fetch_add(&hdr_conflict,1);return;}
    if(!same(p->hdr+4,ap))return;
    if(!p->rx_ctrl.rx_channel_estimate_info_vld || p->rx_ctrl.rx_state!=0)return;
    atomic_fetch_add(&target_csi,1);
    event_t *e=take();if(!e){atomic_fetch_add(&csi_drop,1);return;}
    common(e,CSI,&p->rx_ctrl,p->hdr);unsigned n=p->len,copy=n>CSI_CAP?CSI_CAP:n;
    put16(e->header+32,UPLINK|(n>CSI_CAP?TRUNCATED:0));put16(e->header+34,n);put16(e->header+36,copy);
    memcpy(e->header+52,p->mac,6);put16(e->header+58,p->rx_seq);
    e->header[60]=p->rx_ctrl.rx_channel_estimate_info_vld;e->header[61]=p->first_word_invalid;
    if(n>CSI_CAP)atomic_fetch_add(&csi_truncated,1);
    memcpy(e->data,p->buf,copy);enqueue(e);
}
static uint32_t crc32(const uint8_t *p,unsigned n) {
    uint32_t c=0xffffffffu;
    for(unsigned i=0;i<n;i++){c^=p[i];for(unsigned j=0;j<8;j++)c=(c>>1)^(0xedb88320u&(0u-(c&1)));}
    return ~c;
}
static void emit(event_t *e) {
    static uint8_t wire[HDR+CAP+4];unsigned n=le16(e->header+36);
    configASSERT(n<=CAP);put32(e->header+8,++serial_id);
    memcpy(wire,e->header,HDR);memcpy(wire+HDR,e->data,n);put32(wire+HDR+n,crc32(wire,HDR+n));
    unsigned total=HDR+n+4;int wrote=uart_write_bytes(UART_NUM_0,wire,total);
    if(wrote>0)atomic_fetch_add(&wire_bytes,wrote);
    if(wrote!=(int)total)atomic_fetch_add(&write_errors,1);
    else if(e->header[5]==RAW)atomic_fetch_add(&raw_output,1);
    else if(e->header[5]==CSI)atomic_fetch_add(&csi_output,1);
}
#define U(x) ((unsigned)atomic_load(&(x)))
static void control(unsigned kind) {
    static event_t e;memset(e.header,0,HDR);memcpy(e.header,"CS7R",4);e.header[4]=1;e.header[5]=kind;put16(e.header+6,HDR);
    int n=snprintf((char*)e.data,CAP,"{\"prom_total\":%u,\"prom_data_all\":%u,\"prom_mgmt_all\":%u,\"prom_ctrl_all\":%u,\"prom_misc_all\":%u,\"pair_seen\":%u,\"uplink_data_cb\":%u,\"downlink_eapol_cb\":%u,\"csi_source_cb\":%u,\"pair_frames\":%u,\"eapol_frames\":%u,\"csi_total\":%u,\"target_csi\":%u,\"raw_drop\":%u,\"csi_drop\":%u,\"raw_enqueued\":%u,\"csi_enqueued\":%u,\"raw_output\":%u,\"csi_output\":%u,\"raw_truncated\":%u,\"csi_truncated\":%u,\"csi_empty\":%u,\"hdr_conflict\":%u,\"high_water\":%u,\"write_errors\":%u,\"wire_bytes_before_control\":%u,\"free_heap\":%u,\"min_free_heap\":%u,\"channel\":%u,\"queue_depth\":%u,\"mode\":\"NULL\",\"raw_scope\":\"uplink_data_and_clear_pair_eapol\",\"target\":\"" MACSTR "\",\"ap\":\"" MACSTR "\"}",U(prom_total),U(prom_data_all),U(prom_mgmt_all),U(prom_ctrl_all),U(prom_misc_all),U(pair_seen),U(uplink_data_cb),U(downlink_eapol_cb),U(csi_source_cb),U(pair_frames),U(eapol_frames),U(csi_total),U(target_csi),U(raw_drop),U(csi_drop),U(raw_enqueued),U(csi_enqueued),U(raw_output),U(csi_output),U(raw_truncated),U(csi_truncated),U(csi_empty),U(hdr_conflict),U(high_water),U(write_errors),U(wire_bytes),(unsigned)esp_get_free_heap_size(),(unsigned)esp_get_minimum_free_heap_size(),channel,DEPTH,MAC2STR(target),MAC2STR(ap));
    configASSERT(n>0 && n<CAP);put16(e.header+34,n);put16(e.header+36,n);put64(e.header+16,esp_timer_get_time());emit(&e);
}
static void output_task(void *arg) {
    (void)arg;ulTaskNotifyTake(pdTRUE,portMAX_DELAY);int64_t last=esp_timer_get_time();
    while(atomic_load(&running)||uxQueueMessagesWaiting(events)){
        event_t *e=NULL;if(xQueueReceive(events,&e,pdMS_TO_TICKS(20))==pdTRUE){emit(e);configASSERT(xQueueSend(free_slots,&e,0)==pdTRUE);}
        int64_t now=esp_timer_get_time();if(now-last>=1000000){control(STATS);last=now;}
    }
    control(FINAL);uart_wait_tx_done(UART_NUM_0,pdMS_TO_TICKS(5000));vTaskDelete(NULL);
}
void app_main(void) {
    esp_log_level_set("*",ESP_LOG_NONE);setvbuf(stdout,NULL,_IONBF,0);
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0,2048,16384,0,NULL,0));esp_vfs_dev_uart_use_driver(UART_NUM_0);
    printf("{\"event\":\"READY\",\"version\":\"sniffer-7a-raw-uplink\",\"wire_header\":62,\"raw_cap\":4096,\"csi_cap\":2048}\n");
    char line[160];unsigned ch,m[6],a[6];
    for(;;){
        if(fgets(line,sizeof(line),stdin)&&sscanf(line,"CFG,%u,%x:%x:%x:%x:%x:%x,%x:%x:%x:%x:%x:%x",&ch,&m[0],&m[1],&m[2],&m[3],&m[4],&m[5],&a[0],&a[1],&a[2],&a[3],&a[4],&a[5])==13&&ch>0&&ch<200){
            bool ok=true;for(unsigned i=0;i<6;i++)if(m[i]>255||a[i]>255)ok=false;
            if(ok){channel=ch;for(unsigned i=0;i<6;i++){target[i]=m[i];ap[i]=a[i];}break;}
        }vTaskDelay(pdMS_TO_TICKS(10));
    }
    ESP_ERROR_CHECK(nvs_flash_init());ESP_ERROR_CHECK(esp_netif_init());ESP_ERROR_CHECK(esp_event_loop_create_default());
    wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_NULL));
    ESP_ERROR_CHECK(esp_wifi_set_country_code("CN",false));ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_band_mode(channel>14?WIFI_BAND_MODE_5G_ONLY:WIFI_BAND_MODE_2G_ONLY));ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    free_slots=xQueueCreate(DEPTH,sizeof(event_t*));events=xQueueCreate(DEPTH,sizeof(event_t*));configASSERT(free_slots&&events);
    for(unsigned i=0;i<DEPTH;i++){event_t *e=&pool[i];configASSERT(xQueueSend(free_slots,&e,0)==pdTRUE);}
    wifi_promiscuous_filter_t filter={.filter_mask=WIFI_PROMIS_FILTER_MASK_MGMT|WIFI_PROMIS_FILTER_MASK_CTRL|WIFI_PROMIS_FILTER_MASK_DATA|WIFI_PROMIS_FILTER_MASK_MISC};ESP_ERROR_CHECK(esp_wifi_set_promiscuous_filter(&filter));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_rx_cb(prom_cb));ESP_ERROR_CHECK(esp_wifi_set_channel(channel,WIFI_SECOND_CHAN_NONE));
    uint8_t actual=0;wifi_second_chan_t second;wifi_mode_t mode;
    ESP_ERROR_CHECK(esp_wifi_get_channel(&actual,&second));ESP_ERROR_CHECK(esp_wifi_get_mode(&mode));
    configASSERT(actual==channel && mode==WIFI_MODE_NULL);
    wifi_csi_config_t csi={.enable=1,.acquire_csi_legacy=1,.acquire_csi_force_lltf=0,.acquire_csi_ht20=1,.acquire_csi_ht40=1,.acquire_csi_vht=1,.acquire_csi_su=1,.acquire_csi_mu=1,.acquire_csi_dcm=1,.acquire_csi_beamformed=1,.acquire_csi_he_stbc_mode=2,.val_scale_cfg=0,.dump_ack_en=0,.lltf_bit_mode=0};
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi));ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_cb,NULL));
    TaskHandle_t task=NULL;configASSERT(xTaskCreate(output_task,"raw_uart",6144,NULL,5,&task)==pdPASS);
    atomic_store(&running,true);control(ARMED);
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));ESP_ERROR_CHECK(esp_wifi_set_csi(true));xTaskNotifyGive(task);
    for(;;){if(fgets(line,sizeof(line),stdin)&&strncmp(line,"STOP",4)==0){ESP_ERROR_CHECK(esp_wifi_set_csi(false));ESP_ERROR_CHECK(esp_wifi_set_promiscuous(false));atomic_store(&running,false);break;}vTaskDelay(pdMS_TO_TICKS(10));}
}
