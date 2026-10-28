// CSI-centric HANDSHAKE_DIAG; legacy HANDSHAKE/PROBE modes remain for controlled use.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <inttypes.h>
#include <stddef.h>
#include <limits.h>
#include <errno.h>
#include <stdatomic.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "esp_rom_crc.h"
#include "esp_rom_sys.h"
#include "esp_wifi.h"
#include "esp_wifi_default.h"
#include "esp_mac.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_netif_ip_addr.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "nvs_flash.h"
#include "driver/uart.h"
#include "esp_vfs_dev.h"
#include "lwip/sockets.h"
#include "lwip/inet.h"

#define CAP 2048
#define CSI_CAP 2048
#define DEPTH 24
#define HDR 62
#define RAW 1
#define CSI 6
#define STATS 3
#define ARMED 4
#define FINAL 5
#define TIMELINE 8
#define FCS_ABSENT 1
#define TRUNCATED 2
#define EAPOL 4
#define UPLINK 8
typedef struct { uint8_t header[HDR]; uint8_t data[CAP]; } event_t;
static event_t *pool;
static QueueHandle_t free_slots, events;
static uint8_t target[6], ap[6];
static unsigned channel, serial_id;
enum { MODE_STOP=0, MODE_HANDSHAKE=1, MODE_PROBE=2, MODE_HANDSHAKE_DIAG=3, MODE_HANDSHAKE_DUAL_DIAG=4, MODE_OPEN_AP_POC=5 };
static atomic_bool synthetic_active;
static atomic_uint capture_mode, mode_epoch;
static atomic_uint target_csi_seen,candidate_seen,large_frame_filtered,filter_other,handshake_data_count;
static atomic_uint synthetic_candidates,synthetic_large,synthetic_eapol;
static SemaphoreHandle_t tx_mutex;
static bool configured,synthetic_only,rf_capture_enabled,open_ap_configured,promisc_capture_enabled;
static esp_netif_t *open_ap_netif;
static char open_ap_ssid[33]="CSI-C5-OPEN-POC";
static char open_ap_ip[16]="";
static unsigned open_ap_bandwidth_mhz;
static atomic_bool open_ap_station_connected,udp_server_ready,udp_server_active,udp_server_stop,udp_server_task_running;
static atomic_uint udp_server_error;
static atomic_uint open_pair_csi,open_uplink_csi,open_downlink_csi;
static atomic_uint open_data_frame,open_qos_data,open_non_qos_data;
static atomic_uint open_clear_data,open_protected_data,open_csi_data_enqueued,open_csi_data_output;
static atomic_uint open_csid_magic_seen,open_csid_packet_id_parsed;
static atomic_uint udp_rx_total,udp_valid,udp_crc_ok,udp_crc_fail,udp_invalid,udp_duplicate,udp_unique;
#define UDP_PROBE_PORT 39001
#define UDP_PROBE_PACKET_LEN 48
#define UDP_PROBE_SEEN_CAP 64
static struct { uint32_t run_id, packet_id; } udp_seen[UDP_PROBE_SEEN_CAP];
static unsigned udp_seen_count;
static unsigned synth_rate,synth_seconds;
static const char *control_event="CONFIGURED";
static bool open_ap_setup_failed;
#define U(x) ((unsigned)atomic_load(&(x)))
#define CANDIDATE_MAX 256
static const char *mode_name(void){unsigned m=atomic_load(&capture_mode);return m==MODE_HANDSHAKE?"HANDSHAKE_ONLY":m==MODE_PROBE?"PROBE_CAPTURE":m==MODE_HANDSHAKE_DIAG?"HANDSHAKE_DIAG":m==MODE_HANDSHAKE_DUAL_DIAG?"HANDSHAKE_DUAL_DIAG":m==MODE_OPEN_AP_POC?"OPEN_AP_POC":"STOP";}

static atomic_uint prom_total, pair_frames, eapol_frames, csi_total, target_csi;
static atomic_uint prom_data_all, prom_mgmt_all, prom_ctrl_all, prom_misc_all;
static atomic_uint prom_target_related_data;
static atomic_uint pair_seen, uplink_data_cb, downlink_eapol_cb, csi_source_cb;
// HANDSHAKE_ONLY observability: classify target/AP Data before the raw-candidate gate.
static atomic_uint hs_up_seen, hs_down_seen, hs_up_protected, hs_down_protected;
static atomic_uint hs_up_clear_small, hs_down_clear_small;
static atomic_uint hs_pair_protected, hs_pair_unprotected, hs_pair_len_le256, hs_pair_len_gt256;
static atomic_uint hs_pair_small_accepted, hs_llc_snap_candidate, hs_ethertype_888e_candidate;
static atomic_uint hs_filter_protected, hs_filter_oversize, hs_filter_pair_mismatch, hs_filter_other;
static atomic_uint payload_missing, payload_truncated, prom_dump_gt_sig, prom_dump_eq_sig;
static atomic_uint raw_drop, csi_drop, raw_enqueued, csi_enqueued, raw_output, csi_output;
static atomic_uint raw_truncated, csi_truncated, csi_empty, hdr_conflict, high_water, write_errors, wire_bytes;

// Pure observational counters
static atomic_uint csi_cb_total, csi_null, csi_source_target, csi_source_other;
static atomic_uint csi_hdr_present, csi_buf_present;
static atomic_uint csi_valid_channel_estimate, csi_rxstate_ok, csi_target_valid;
static atomic_uint rx_11b, rx_legacy, rx_ht, rx_vht, rx_other;
// CSI-centric HANDSHAKE_DIAG keeps the selected 802.11 frame and CSI in one record.
static atomic_uint diag_pair_seen, diag_uplink, diag_downlink, diag_protected, diag_clear;
static atomic_uint diag_len_le256, diag_len_gt256, diag_llc_snap, diag_ethertype_888e;
static atomic_uint diag_candidate_enqueued, diag_reject_layout, diag_reject_length;
static atomic_uint diag_reject_protected, diag_reject_llc, diag_reject_ethertype, diag_invalid_csi;
static atomic_uint diag_payload_available, diag_payload_missing;
static uint8_t actual_chan;
static wifi_second_chan_t actual_sec;
static wifi_mode_t actual_mode;
static bool channel_readback_ok;

#define DUAL_METRICS(X) \
    X(prom_target_related) X(prom_pair) X(prom_up) X(prom_down) \
    X(prom_protected) X(prom_clear) X(prom_len_le256) X(prom_len_gt256) \
    X(prom_llc_snap) X(prom_ethertype_888e) X(prom_eapol_candidate) \
    X(prom_raw_enqueued) X(prom_raw_output) X(prom_raw_drop) X(prom_raw_truncated) \
    X(csi_pair) X(csi_up) X(csi_down) X(csi_protected) X(csi_clear) \
    X(csi_payload_available) X(csi_payload_missing) X(csi_len_le256) X(csi_len_gt256) \
    X(csi_llc_snap) X(csi_ethertype_888e) X(csi_valid) X(csi_invalid) \
    X(csi_layout_reject) X(csi_data_enqueued) X(csi_data_output) X(csi_drop) \
    X(csi_reject_length) X(write_errors)
#define DECL_DUAL_METRIC(name) atomic_uint name;
typedef struct { DUAL_METRICS(DECL_DUAL_METRIC) } dual_metrics_t;
#undef DECL_DUAL_METRIC
static dual_metrics_t dual_total, dual_window;
static atomic_bool dual_capture_active;
static uint64_t timeline_last_us;
static uint32_t timeline_bucket_id;
#define TIMELINE_BUCKET_US 200000
#define DUAL_ADD(name) do { \
    if(atomic_load(&dual_capture_active)) { \
        atomic_fetch_add(&dual_total.name,1); \
        atomic_fetch_add(&dual_window.name,1); \
    } \
} while(0)

static uint16_t le16(const uint8_t *p) { return p[0] | (p[1]<<8); }
static void put16(uint8_t *p, unsigned v) { p[0]=v; p[1]=v>>8; }
static void put32(uint8_t *p, uint32_t v) { for(unsigned i=0;i<4;i++) p[i]=v>>(8*i); }
static void put64(uint8_t *p, uint64_t v) { for(unsigned i=0;i<8;i++) p[i]=v>>(8*i); }
static uint32_t get32(const uint8_t *p) { return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24); }
static uint64_t get64(const uint8_t *p) { return (uint64_t)get32(p)|((uint64_t)get32(p+4)<<32); }
static uint32_t crc32(const uint8_t*p,unsigned n){return esp_rom_crc32_le(0,p,n);}
static bool same(const uint8_t *a,const uint8_t *b) { return memcmp(a,b,6)==0; }
static unsigned header_length(const uint8_t *p, unsigned n) {
    if(n<24) return 0;
    uint16_t fc=le16(p); if(((fc>>2)&3)!=2) return 0;
    unsigned h=24;
    if((fc&0x300)==0x300) h+=6;
    if(fc&0x80) { h+=2; if(fc&0x8000) h+=4; }
    return n>=h?h:0;
}
static void exact_infrastructure_pair(const uint8_t *p,bool *up,bool *down) {
    uint16_t fc=le16(p);bool tods=(fc&0x0100)!=0,fromds=(fc&0x0200)!=0;
    *up=tods&&!fromds&&same(p+4,ap)&&same(p+10,target);
    *down=!tods&&fromds&&same(p+4,target)&&same(p+10,ap);
}
static bool is_eapol(const uint8_t *p,unsigned n,unsigned h) {
    static const uint8_t llc[]={0xaa,0xaa,3,0,0,0,0x88,0x8e};
    // Protected/A-MSDU/fragmented bodies are never guessed to contain clear LLC.
    uint16_t fc=le16(p);
    if(fc&0x4000 || fc&0x400 || (le16(p+22)&15)) return false;
    unsigned qos=24+(((fc&0x300)==0x300)?6:0);
    if((fc&0x80) && (p[qos]&0x80)) return false;
    return n>=h+8 && memcmp(p+h,llc,8)==0;
}
static bool has_llc_snap_candidate(const uint8_t *p,unsigned n,unsigned h) {
    static const uint8_t snap[]={0xaa,0xaa,3,0,0,0};
    uint16_t fc=le16(p);
    if(fc&0x4000 || fc&0x400 || (le16(p+22)&15)) return false;
    unsigned qos=24+(((fc&0x300)==0x300)?6:0);
    if((fc&0x80) && (p[qos]&0x80)) return false;
    return n>=h+6 && memcmp(p+h,snap,6)==0;
}
static bool has_ethertype_888e_candidate(const uint8_t *p,unsigned n,unsigned h) {
    static const uint8_t ethertype[]={0x88,0x8e};
    return has_llc_snap_candidate(p,n,h) && n>=h+8 && memcmp(p+h+6,ethertype,2)==0;
}
static void emit(event_t *e);
static void scan_open_csid(const uint8_t *frame,unsigned n) {
    for(unsigned i=0;i+UDP_PROBE_PACKET_LEN<=n;i++){
        const uint8_t *p=frame+i;
        if(memcmp(p,"CSID",4)!=0)continue;
        atomic_fetch_add(&open_csid_magic_seen,1);
        if(p[4]!=1||p[5]!=28||le16(p+6)!=0||le16(p+24)!=16||le16(p+26)!=0)continue;
        if(get32(p+44)!=crc32(p,44))continue;
        uint32_t packet_id=get32(p+12);bool pattern=true;
        for(unsigned j=0;j<16;j++)if(p[28+j]!=(uint8_t)(packet_id+j)){pattern=false;break;}
        if(pattern)atomic_fetch_add(&open_csid_packet_id_parsed,1);
        return;
    }
}
static void open_ap_stats_control(const char *event_name) {
    xSemaphoreTakeRecursive(tx_mutex,portMAX_DELAY);
    static event_t e;memset(e.header,0,HDR);
    memcpy(e.header,"CS8R",4);e.header[4]=1;e.header[5]=7;put16(e.header+6,HDR);
    int n=snprintf((char*)e.data,CAP,
      "{\"event\":\"%s\",\"mode\":\"%s\",\"ssid\":\"%s\",\"ap_ip\":\"%s\",\"actual_channel\":%u,\"bandwidth_mhz\":%u,\"channel_readback_ok\":%s,\"station_connected\":%s,\"udp_server_ready\":%s,\"udp_server_error\":%u,"
      "\"open_pair_csi\":%u,\"open_uplink_csi\":%u,\"open_downlink_csi\":%u,\"open_data_frame\":%u,\"open_qos_data\":%u,\"open_non_qos_data\":%u,\"open_clear_data\":%u,\"open_protected_data\":%u,\"open_csi_data_enqueued\":%u,\"open_csi_data_output\":%u,\"open_csid_magic_seen\":%u,\"open_csid_packet_id_parsed\":%u,"
      "\"udp_rx_total\":%u,\"udp_valid\":%u,\"udp_crc_ok\":%u,\"udp_crc_fail\":%u,\"udp_invalid\":%u,\"udp_duplicate\":%u,\"udp_unique\":%u,\"queue_drop\":%u,\"raw_drop\":%u,\"csi_drop\":%u,\"write_errors\":%u,\"raw_truncated\":%u,\"csi_truncated\":%u,\"payload_truncated\":%u,\"free_heap\":%u,\"min_free_heap\":%u}",
      event_name,mode_name(),open_ap_ssid,open_ap_ip,(unsigned)actual_chan,open_ap_bandwidth_mhz,channel_readback_ok?"true":"false",
      atomic_load(&open_ap_station_connected)?"true":"false",atomic_load(&udp_server_ready)?"true":"false",U(udp_server_error),
      U(open_pair_csi),U(open_uplink_csi),U(open_downlink_csi),U(open_data_frame),U(open_qos_data),U(open_non_qos_data),U(open_clear_data),U(open_protected_data),U(open_csi_data_enqueued),U(open_csi_data_output),U(open_csid_magic_seen),U(open_csid_packet_id_parsed),
      U(udp_rx_total),U(udp_valid),U(udp_crc_ok),U(udp_crc_fail),U(udp_invalid),U(udp_duplicate),U(udp_unique),U(raw_drop)+U(csi_drop),U(raw_drop),U(csi_drop),U(write_errors),U(raw_truncated),U(csi_truncated),U(payload_truncated),(unsigned)esp_get_free_heap_size(),(unsigned)esp_get_minimum_free_heap_size());
    configASSERT(n>0&&n<CAP);put16(e.header+34,n);put16(e.header+36,n);put64(e.header+16,esp_timer_get_time());emit(&e);
    xSemaphoreGiveRecursive(tx_mutex);
}
static void open_ap_udp_rx_control(uint32_t run_id,uint32_t packet_id,uint64_t sender_ns,
                                   uint64_t rx_us,bool valid,bool crc_ok,bool duplicate,unsigned length) {
    xSemaphoreTakeRecursive(tx_mutex,portMAX_DELAY);
    static event_t e;memset(e.header,0,HDR);
    memcpy(e.header,"CS8R",4);e.header[4]=1;e.header[5]=7;put16(e.header+6,HDR);
    int n=snprintf((char*)e.data,CAP,
      "{\"event\":\"UDP_RX\",\"run_id\":%" PRIu32 ",\"packet_id\":%" PRIu32 ",\"sender_mono_ns\":%llu,\"esp_rx_us\":%llu,\"valid\":%s,\"crc_ok\":%s,\"duplicate\":%s,\"datagram_len\":%u}",
      run_id,packet_id,(unsigned long long)sender_ns,(unsigned long long)rx_us,valid?"true":"false",crc_ok?"true":"false",duplicate?"true":"false",length);
    configASSERT(n>0&&n<CAP);put16(e.header+34,n);put16(e.header+36,n);put64(e.header+16,rx_us);emit(&e);
    xSemaphoreGiveRecursive(tx_mutex);
}
static event_t *take(void) {
    event_t *e=NULL; if(xQueueReceive(free_slots,&e,0)!=pdTRUE) return NULL;
    memset(e->header,0,HDR); return e;
}
static void common(event_t *e,unsigned kind,const wifi_pkt_rx_ctrl_t *m,const uint8_t *h) {
    uint8_t *p=e->header;memcpy(p,"CS8R",4);p[4]=1;p[5]=kind;put16(p+6,HDR);
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
    if(atomic_load(&capture_mode)==MODE_STOP)return;
    atomic_fetch_add(&prom_total,1);
    if(kind==WIFI_PKT_DATA)atomic_fetch_add(&prom_data_all,1);
    else if(kind==WIFI_PKT_MGMT)atomic_fetch_add(&prom_mgmt_all,1);
    else if(kind==WIFI_PKT_CTRL)atomic_fetch_add(&prom_ctrl_all,1);
    else atomic_fetch_add(&prom_misc_all,1);
    if(!buf||kind!=WIFI_PKT_DATA)return;
    const wifi_promiscuous_pkt_t *p=buf;wifi_pkt_rx_ctrl_t meta=p->rx_ctrl;
    if(meta.dump_len>meta.sig_len)atomic_fetch_add(&prom_dump_gt_sig,1);
    if(meta.dump_len==meta.sig_len)atomic_fetch_add(&prom_dump_eq_sig,1);
    unsigned n=meta.sig_len<meta.dump_len?meta.sig_len:meta.dump_len;
    unsigned h=header_length(p->payload,n);if(!h)return;
    uint16_t fc=le16(p->payload);unsigned mode=atomic_load(&capture_mode);
    bool target_related=same(p->payload+10,target)||same(p->payload+4,target);
    if(target_related){atomic_fetch_add(&prom_target_related_data,1);DUAL_ADD(prom_target_related);}

    if(mode==MODE_HANDSHAKE_DUAL_DIAG) {
        bool up=false,down=false;exact_infrastructure_pair(p->payload,&up,&down);
        if(!up&&!down)return;
        atomic_fetch_add(&pair_seen,1);DUAL_ADD(prom_pair);
        if(up){DUAL_ADD(prom_up);}else{DUAL_ADD(prom_down);}
        if(n<=CANDIDATE_MAX)DUAL_ADD(prom_len_le256);else DUAL_ADD(prom_len_gt256);
        bool protected_frame=(fc&0x4000)!=0;
        if(protected_frame)DUAL_ADD(prom_protected);else DUAL_ADD(prom_clear);
        bool llc_snap=has_llc_snap_candidate(p->payload,n,h);
        bool ethertype=has_ethertype_888e_candidate(p->payload,n,h);
        if(llc_snap)DUAL_ADD(prom_llc_snap);
        if(ethertype)DUAL_ADD(prom_ethertype_888e);
        bool eapol=ethertype&&is_eapol(p->payload,n,h);
        if(!eapol)return; // Protected/background Data and clear non-EAPOL never enter RAW.
        DUAL_ADD(prom_eapol_candidate);
        atomic_fetch_add(&pair_frames,1);atomic_fetch_add(&eapol_frames,1);
        if(n>CAP){atomic_fetch_add(&raw_truncated,1);DUAL_ADD(prom_raw_truncated);return;}
        if(up)atomic_fetch_add(&uplink_data_cb,1);else atomic_fetch_add(&downlink_eapol_cb,1);
        event_t *e=take();if(!e){atomic_fetch_add(&raw_drop,1);DUAL_ADD(prom_raw_drop);return;}
        common(e,RAW,&meta,p->payload);put16(e->header+32,EAPOL|(up?UPLINK:0)); // FCS semantics remain unconfirmed.
        put16(e->header+34,n);put16(e->header+36,n);
        memcpy(e->data,p->payload,n);DUAL_ADD(prom_raw_enqueued);enqueue(e);return;
    }

    bool station_uplink=same(p->payload+10,target);
    bool up=station_uplink&&same(p->payload+4,ap);
    bool down=!station_uplink&&same(p->payload+10,ap)&&same(p->payload+4,target);
    if(up||down)atomic_fetch_add(&pair_seen,1);
    if(!target_related)return;
    // CSI-centric HANDSHAKE_DIAG deliberately counts but does not export promisc frames.
    if(mode==MODE_HANDSHAKE_DIAG)return;
    bool eapol=is_eapol(p->payload,n,h);
    bool llc_snap_candidate=has_llc_snap_candidate(p->payload,n,h);
    bool ethertype_888e_candidate=has_ethertype_888e_candidate(p->payload,n,h);
    bool pair_small=(mode==MODE_HANDSHAKE && (up||down) && n<=CANDIDATE_MAX && !(fc&0x4000));
    if(mode==MODE_HANDSHAKE) {
        if(llc_snap_candidate) atomic_fetch_add(&hs_llc_snap_candidate,1);
        if(ethertype_888e_candidate) atomic_fetch_add(&hs_ethertype_888e_candidate,1);
        if(up) atomic_fetch_add(&hs_up_seen,1);
        if(down) atomic_fetch_add(&hs_down_seen,1);
        if(up||down) {
            if(n<=CANDIDATE_MAX) atomic_fetch_add(&hs_pair_len_le256,1);
            else atomic_fetch_add(&hs_pair_len_gt256,1);
            if(fc&0x4000) {
                atomic_fetch_add(&hs_pair_protected,1);
                if(up) atomic_fetch_add(&hs_up_protected,1);
                else atomic_fetch_add(&hs_down_protected,1);
            } else {
                atomic_fetch_add(&hs_pair_unprotected,1);
                if(n<=CANDIDATE_MAX) {
                    if(up) atomic_fetch_add(&hs_up_clear_small,1);
                    else atomic_fetch_add(&hs_down_clear_small,1);
                }
            }
        }
        if(pair_small) atomic_fetch_add(&hs_pair_small_accepted,1);
    }
    if(!eapol && !pair_small) {
        if(mode==MODE_HANDSHAKE) {
            if(fc&0x4000) atomic_fetch_add(&hs_filter_protected,1);
            else if(!(up||down)) atomic_fetch_add(&hs_filter_pair_mismatch,1);
            else if(n>CANDIDATE_MAX) atomic_fetch_add(&hs_filter_oversize,1);
            else atomic_fetch_add(&hs_filter_other,1);
        }
        return;
    }
    atomic_fetch_add(&pair_frames,1);
    if(eapol)atomic_fetch_add(&eapol_frames,1);
    if(n>CAP){atomic_fetch_add(&raw_truncated,1);return;}
    if(station_uplink)atomic_fetch_add(&uplink_data_cb,1);else atomic_fetch_add(&downlink_eapol_cb,1);
    event_t *e=take();if(!e){atomic_fetch_add(&raw_drop,1);return;}
    common(e,RAW,&meta,p->payload);unsigned copy=n>CAP?CAP:n;
    put16(e->header+32,(eapol?EAPOL:0)|(station_uplink?UPLINK:0)|(copy<n?TRUNCATED:0));
    put16(e->header+34,n);put16(e->header+36,copy);
    if(copy<n)atomic_fetch_add(&raw_truncated,1);
    memcpy(e->data,p->payload,copy);enqueue(e);
}
static void csi_diag_cb(wifi_csi_info_t *p,bool eapol_only) {
    wifi_pkt_rx_ctrl_t meta=p->rx_ctrl;
    if(!p->hdr){atomic_fetch_add(&diag_reject_layout,1);return;}
    uint8_t first24[24];memcpy(first24,p->hdr,sizeof(first24));
    unsigned hl=header_length(first24,UINT16_MAX);
    if(hl<24||hl>36){atomic_fetch_add(&diag_reject_layout,1);return;}
    uint8_t hdr[36];memcpy(hdr,p->hdr,hl);
    if(header_length(hdr,hl)!=hl){atomic_fetch_add(&diag_reject_layout,1);return;}

    uint16_t fc=le16(hdr);bool up=false,down=false;exact_infrastructure_pair(hdr,&up,&down);
    if(!up&&!down)return; // Exact Jetson↔AP pair only; no third-party frames are exported.
    bool open_mode=atomic_load(&capture_mode)==MODE_OPEN_AP_POC;
    atomic_fetch_add(&diag_pair_seen,1);
    if(up)atomic_fetch_add(&diag_uplink,1);else atomic_fetch_add(&diag_downlink,1);
    if(open_mode){
        atomic_fetch_add(&open_pair_csi,1);
        if(up)atomic_fetch_add(&open_uplink_csi,1);else atomic_fetch_add(&open_downlink_csi,1);
        if((fc&0x000c)==0x0008){
            atomic_fetch_add(&open_data_frame,1);
            if((fc&0x0080)!=0)atomic_fetch_add(&open_qos_data,1);
            else atomic_fetch_add(&open_non_qos_data,1);
            if(fc&0x4000)atomic_fetch_add(&open_protected_data,1);
            else atomic_fetch_add(&open_clear_data,1);
        }
    }
    if(!eapol_only){DUAL_ADD(csi_pair);if(up)DUAL_ADD(csi_up);else DUAL_ADD(csi_down);}

    if(meta.rx_channel_estimate_info_vld)atomic_fetch_add(&csi_valid_channel_estimate,1);
    if(meta.rx_state==0)atomic_fetch_add(&csi_rxstate_ok,1);
    bool csi_valid=meta.rx_channel_estimate_info_vld&&meta.rx_state==0&&p->buf&&p->len;
    if(csi_valid){
        atomic_fetch_add(&csi_target_valid,1);
        atomic_fetch_add(&target_csi_seen,1);
        atomic_fetch_add(&csi_buf_present,1);
        if(!eapol_only)DUAL_ADD(csi_valid);
    }else{
        atomic_fetch_add(&diag_invalid_csi,1);
        if(!eapol_only)DUAL_ADD(csi_invalid);
        if(!p->buf||!p->len)atomic_fetch_add(&csi_empty,1);
    }

    bool protected_frame=(fc&0x4000)!=0;
    if(protected_frame){
        atomic_fetch_add(&diag_protected,1);
        if(eapol_only){atomic_fetch_add(&diag_reject_protected,1);return;}
        DUAL_ADD(csi_protected);
    }else{
        atomic_fetch_add(&diag_clear,1);
        if(!eapol_only)DUAL_ADD(csi_clear);
    }
    if(p->payload&&p->payload_len){atomic_fetch_add(&diag_payload_available,1);if(!eapol_only)DUAL_ADD(csi_payload_available);}
    else {atomic_fetch_add(&diag_payload_missing,1);if(!eapol_only)DUAL_ADD(csi_payload_missing);}
    if(p->payload_len>CANDIDATE_MAX){
        atomic_fetch_add(&diag_len_gt256,1);atomic_fetch_add(&diag_reject_length,1);
        if(!eapol_only)DUAL_ADD(csi_len_gt256);
        return;
    }
    atomic_fetch_add(&diag_len_le256,1);if(!eapol_only)DUAL_ADD(csi_len_le256);
    if(!p->payload||!p->payload_len){
        atomic_fetch_add(&diag_reject_layout,1);if(!eapol_only)DUAL_ADD(csi_layout_reject);return;
    }
    // Handshake-only peeks for clear EAPOL and therefore rejects incomplete MSDUs.
    // DUAL_DIAG preserves Protected, fragmented and A-MSDU MPDUs for later host analysis.
    if(eapol_only&&((fc&0x0400)||(le16(hdr+22)&15))){atomic_fetch_add(&diag_reject_layout,1);return;}
    unsigned qosoff=24;
    if(eapol_only&&(fc&0x0080)&&(hdr[qosoff]&0x80)){atomic_fetch_add(&diag_reject_layout,1);return;}

    intptr_t delta=(intptr_t)(uintptr_t)p->payload-(intptr_t)(uintptr_t)p->hdr;
    if(delta<24||delta>(intptr_t)hl){atomic_fetch_add(&diag_reject_layout,1);if(!eapol_only)DUAL_ADD(csi_layout_reject);return;}
    unsigned overlap=hl-(unsigned)delta;
    unsigned needed=overlap+(eapol_only?8:1);
    if(p->payload_len<needed){atomic_fetch_add(&diag_reject_layout,1);if(!eapol_only)DUAL_ADD(csi_layout_reject);return;}
    if(overlap&&memcmp(hdr+(unsigned)delta,p->payload,overlap)!=0){
        atomic_fetch_add(&diag_reject_layout,1);if(!eapol_only)DUAL_ADD(csi_layout_reject);return;
    }
    if(open_mode){
        uint8_t frame[36+CANDIDATE_MAX];unsigned frame_len=(unsigned)delta+p->payload_len;
        if(frame_len<=sizeof(frame)){
            memcpy(frame,hdr,hl);
            unsigned tail=p->payload_len-overlap;
            if(tail)memcpy(frame+hl,p->payload+overlap,tail);
            scan_open_csid(frame,frame_len);
        }
    }
    const uint8_t *llc=p->payload+overlap;bool llc_snap=false,ethertype=false;
    if(!protected_frame&&!(fc&0x0400)&&!(le16(hdr+22)&15)&&!((fc&0x0080)&&(hdr[qosoff]&0x80))){
        static const uint8_t snap[]={0xaa,0xaa,3,0,0,0};
        llc_snap=p->payload_len>=overlap+6&&memcmp(llc,snap,sizeof(snap))==0;
        ethertype=llc_snap&&p->payload_len>=overlap+8&&llc[6]==0x88&&llc[7]==0x8e;
        if(llc_snap){atomic_fetch_add(&diag_llc_snap,1);if(!eapol_only)DUAL_ADD(csi_llc_snap);}
        if(ethertype){atomic_fetch_add(&diag_ethertype_888e,1);if(!eapol_only)DUAL_ADD(csi_ethertype_888e);}
    }
    if(eapol_only&&!llc_snap){atomic_fetch_add(&diag_reject_llc,1);return;}
    if(eapol_only&&!ethertype){atomic_fetch_add(&diag_reject_ethertype,1);return;}
    if(!eapol_only&&!csi_valid)return;

    unsigned origp=p->payload_len,origc=p->len;
    unsigned base=20+sizeof(meta)+hl;
    if(base+origp+origc>CAP){atomic_fetch_add(&diag_reject_length,1);if(!eapol_only)DUAL_ADD(csi_reject_length);return;}
    unsigned cc=(p->buf&&origc)?origc:0;

    event_t *e=take();if(!e){atomic_fetch_add(&csi_drop,1);if(!eapol_only)DUAL_ADD(csi_drop);return;}
    memcpy(e->data+20,&meta,sizeof(meta));
    memcpy(e->data+20+sizeof(meta),hdr,hl);
    memcpy(e->data+base,p->payload,origp);
    if(cc)memcpy(e->data+base+origp,p->buf,cc);
    put16(e->data,hl);put16(e->data+2,origp);put16(e->data+4,origp);
    put16(e->data+6,origc);put16(e->data+8,cc);put16(e->data+10,sizeof(meta));
    put16(e->data+12,meta.sig_len);put16(e->data+14,meta.dump_len);
    put32(e->data+16,(uint32_t)(int32_t)delta);
    common(e,CSI,&meta,hdr);
    if(origc!=cc)atomic_fetch_add(&csi_truncated,1);
    put16(e->header+32,(up?UPLINK:0)|((origc!=cc)?TRUNCATED:0));
    unsigned copied=base+origp+cc,original=base+origp+origc;
    put16(e->header+34,original>UINT16_MAX?UINT16_MAX:original);
    put16(e->header+36,copied);
    memcpy(e->header+52,p->mac,6);put16(e->header+58,p->rx_seq);
    e->header[60]=meta.rx_channel_estimate_info_vld;e->header[61]=p->first_word_invalid;
    enqueue(e);atomic_fetch_add(&diag_candidate_enqueued,1);
    if(open_mode)atomic_fetch_add(&open_csi_data_enqueued,1);
    if(!eapol_only)DUAL_ADD(csi_data_enqueued);
}
static void csi_cb(void *ctx,wifi_csi_info_t *p) {
    (void)ctx;
    atomic_fetch_add(&csi_cb_total, 1);
    if(atomic_load(&capture_mode)==MODE_STOP)return;
    atomic_fetch_add(&csi_total,1);
    if(!p){
        atomic_fetch_add(&csi_null, 1);
        atomic_fetch_add(&csi_empty, 1);
        return;
    }
    uint8_t fmt = p->rx_ctrl.cur_bb_format;
    if(fmt == 0) atomic_fetch_add(&rx_11b, 1);
    else if(fmt == 1) atomic_fetch_add(&rx_legacy, 1);
    else if(fmt == 2) atomic_fetch_add(&rx_ht, 1);
    else if(fmt == 3) atomic_fetch_add(&rx_vht, 1);
    else atomic_fetch_add(&rx_other, 1);

    unsigned mode=atomic_load(&capture_mode);
    if(mode==MODE_OPEN_AP_POC){csi_diag_cb(p,false);return;}
    if(!same(p->mac,target)){
        atomic_fetch_add(&csi_source_other, 1);
    } else {
        atomic_fetch_add(&csi_source_target, 1);
        atomic_fetch_add(&csi_source_cb,1);
    }

    // Select both directions from 802.11 addresses/DS bits in diagnostic modes.
    if(mode==MODE_HANDSHAKE_DIAG){csi_diag_cb(p,true);return;}
    if(mode==MODE_HANDSHAKE_DUAL_DIAG){csi_diag_cb(p,false);return;}
    if(!same(p->mac,target))return;

    if(!p->buf||!p->len){
        atomic_fetch_add(&csi_empty,1);
        return;
    }
    atomic_fetch_add(&csi_buf_present, 1);

    if(!p->hdr)return;
    atomic_fetch_add(&csi_hdr_present, 1);

    wifi_pkt_rx_ctrl_t meta=p->rx_ctrl;
    uint8_t h24[24];memcpy(h24,p->hdr,24);
    unsigned hl=header_length(h24,UINT16_MAX);if(!hl)return;
    if(!same(h24+10,target)||!same(h24+4,ap)){atomic_fetch_add(&hdr_conflict,1);return;}

    if(meta.rx_channel_estimate_info_vld) atomic_fetch_add(&csi_valid_channel_estimate, 1);
    if(meta.rx_state == 0) atomic_fetch_add(&csi_rxstate_ok, 1);

    if(!meta.rx_channel_estimate_info_vld||meta.rx_state!=0)return;
    atomic_fetch_add(&csi_target_valid, 1);
    atomic_fetch_add(&target_csi_seen,1);

    if(mode==MODE_HANDSHAKE){atomic_fetch_add(&handshake_data_count,1);return;}
    if(!p->payload || !p->payload_len){atomic_fetch_add(&filter_other,1);return;}
    if(p->payload_len>CANDIDATE_MAX){atomic_fetch_add(&large_frame_filtered,1);return;}
    if(20+sizeof(meta)+hl+p->payload_len+p->len>CAP){atomic_fetch_add(&filter_other,1);return;}
    atomic_fetch_add(&candidate_seen,1);
    atomic_fetch_add(&target_csi,1);
    event_t *e=take();if(!e){atomic_fetch_add(&csi_drop,1);return;}
    unsigned origp=p->payload_len,origc=p->len;
    unsigned base=20+sizeof(meta)+hl;
    unsigned limit=CAP-base<CSI_CAP?CAP-base:CSI_CAP;
    unsigned cc=origc>limit?limit:origc;
    unsigned pc=origp>CAP-base-cc?CAP-base-cc:origp;
    if(!p->payload&&origp){pc=0;atomic_fetch_add(&payload_missing,1);}
    // All parts belong to this one callback. Never use a later callback to fill gaps.
    memcpy(e->data+20+sizeof(meta),p->hdr,hl);
    if(pc)memcpy(e->data+base,p->payload,pc);
    memcpy(e->data+base+pc,p->buf,cc);
    memcpy(e->data+20,&meta,sizeof(meta));
    put16(e->data,hl);put16(e->data+2,origp);put16(e->data+4,pc);
    put16(e->data+6,origc);put16(e->data+8,cc);put16(e->data+10,sizeof(meta));
    put16(e->data+12,meta.sig_len);put16(e->data+14,meta.dump_len);
    int64_t delta=(int64_t)(uintptr_t)p->payload-(int64_t)(uintptr_t)p->hdr;
    put32(e->data+16,(delta>=INT32_MIN&&delta<=INT32_MAX)?(uint32_t)(int32_t)delta:0x80000000u);
    common(e,CSI,&meta,h24);
    if(origc!=cc)atomic_fetch_add(&csi_truncated,1);
    if(origp!=pc)atomic_fetch_add(&payload_truncated,1);
    unsigned copied=base+pc+cc;
    unsigned original=base+origp+origc;
    put16(e->header+32,UPLINK|((pc!=origp||cc!=origc)?TRUNCATED:0));
    put16(e->header+34,original>UINT16_MAX?UINT16_MAX:original);put16(e->header+36,copied);
    memcpy(e->header+52,p->mac,6);put16(e->header+58,p->rx_seq);
    e->header[60]=meta.rx_channel_estimate_info_vld;e->header[61]=p->first_word_invalid;
    enqueue(e);
}
static void emit(event_t *e) {
    xSemaphoreTakeRecursive(tx_mutex,portMAX_DELAY);
    static uint8_t wire[HDR+CAP+4];unsigned n=le16(e->header+36);
    if(synthetic_only)put16(e->header+32,le16(e->header+32)|16);
    configASSERT(n<=CAP);put32(e->header+8,++serial_id);
    memcpy(wire,e->header,HDR);memcpy(wire+HDR,e->data,n);put32(wire+HDR+n,crc32(wire,HDR+n));
    unsigned total=HDR+n+4;int wrote=uart_write_bytes(UART_NUM_0,wire,total);
    if(wrote>0)atomic_fetch_add(&wire_bytes,wrote);
    if(wrote!=(int)total){atomic_fetch_add(&write_errors,1);DUAL_ADD(write_errors);}
    else if(e->header[5]==RAW){atomic_fetch_add(&raw_output,1);DUAL_ADD(prom_raw_output);}
    else if(e->header[5]==CSI){atomic_fetch_add(&csi_output,1);DUAL_ADD(csi_data_output);if(open_ap_configured)atomic_fetch_add(&open_csi_data_output,1);}
    xSemaphoreGiveRecursive(tx_mutex);
}
#define DUAL_JSON_KEY(name) "\"" #name "\":%u,"
#define DUAL_JSON_LOAD(name) (unsigned)atomic_load(&metrics->name),
#define DUAL_JSON_TAKE(name) (unsigned)atomic_exchange(&metrics->name,0),
static void emit_dual_metrics(const char *event,dual_metrics_t *metrics,uint64_t start_us,uint64_t end_us,bool take_window) {
    static event_t e;memset(e.header,0,HDR);
    memcpy(e.header,"CS8R",4);e.header[4]=1;e.header[5]=take_window?TIMELINE:7;put16(e.header+6,HDR);
    int n;
    if(take_window){
        n=snprintf((char*)e.data,CAP,
          "{\"event\":\"%s\",\"mode\":\"HANDSHAKE_DUAL_DIAG\",\"nominal_bucket_us\":%u," DUAL_METRICS(DUAL_JSON_KEY)
          "\"bucket_id\":%u,\"start_us\":%llu,\"end_us\":%llu,\"actual_span_us\":%llu}",
          event,TIMELINE_BUCKET_US,DUAL_METRICS(DUAL_JSON_TAKE) (unsigned)timeline_bucket_id++,
          (unsigned long long)start_us,(unsigned long long)end_us,(unsigned long long)(end_us-start_us));
    }else{
        n=snprintf((char*)e.data,CAP,
          "{\"event\":\"%s\",\"mode\":\"HANDSHAKE_DUAL_DIAG\",\"nominal_bucket_us\":%u," DUAL_METRICS(DUAL_JSON_KEY)
          "\"bucket_id\":%u,\"start_us\":%llu,\"end_us\":%llu}",
          event,TIMELINE_BUCKET_US,DUAL_METRICS(DUAL_JSON_LOAD) (unsigned)timeline_bucket_id,
          (unsigned long long)start_us,(unsigned long long)end_us);
    }
    configASSERT(n>0&&n<CAP);put16(e.header+34,n);put16(e.header+36,n);put64(e.header+16,end_us);emit(&e);
}
static void timeline_flush(uint64_t now_us,bool final_partial) {
    if(!timeline_last_us){timeline_last_us=now_us;return;}
    if(now_us<=timeline_last_us||(!final_partial&&now_us-timeline_last_us<TIMELINE_BUCKET_US))return;
    uint64_t start=timeline_last_us;timeline_last_us=now_us;
    emit_dual_metrics("TIMELINE",&dual_window,start,now_us,true);
}
static void dual_stats(uint64_t now_us) {
    emit_dual_metrics("DUAL_STATS",&dual_total,timeline_last_us,now_us,false);
}
#define DUAL_ZERO(name) do { atomic_store(&dual_total.name,0);atomic_store(&dual_window.name,0); } while(0);
static void dual_reset(uint64_t now_us) {
    DUAL_METRICS(DUAL_ZERO)
    timeline_bucket_id=0;timeline_last_us=now_us;
}
#undef DUAL_ZERO
#undef DUAL_JSON_KEY
#undef DUAL_JSON_LOAD
#undef DUAL_JSON_TAKE

static void control(unsigned kind){
 xSemaphoreTakeRecursive(tx_mutex,portMAX_DELAY);
 static event_t e;memset(e.header,0,HDR);memcpy(e.header,"CS8R",4);e.header[4]=1;e.header[5]=kind;put16(e.header+6,HDR);
 int n=snprintf((char*)e.data,CAP,
 "{\"event\":\"%s\",\"mode\":\"%s\",\"mode_epoch\":%u,\"counters_reset\":false,\"synthetic\":%s,\"rf_capture_enabled\":%s,"
 "\"target_csi_seen\":%u,\"candidate_seen\":%u,\"candidate_enqueued\":%u,\"candidate_output\":%u,\"large_frame_filtered\":%u,\"filter_other\":%u,\"handshake_data_count\":%u,"
 "\"queue_drop\":%u,\"csi_total\":%u,\"target_csi\":%u,\"raw_drop\":%u,\"csi_drop\":%u,\"raw_enqueued\":%u,\"csi_enqueued\":%u,\"raw_output\":%u,\"csi_output\":%u,\"eapol_frames\":%u,"
 "\"raw_truncated\":%u,\"csi_truncated\":%u,\"payload_truncated\":%u,\"payload_missing\":%u,\"csi_empty\":%u,\"hdr_conflict\":%u,\"write_errors\":%u,\"high_water\":%u,"
 "\"free_heap\":%u,\"min_free_heap\":%u,\"queue_depth\":%u,\"queue_pending\":%u,\"candidate_max\":%u,\"channel\":%u,\"synth_rate\":%u,\"synth_seconds\":%u,\"synthetic_candidates\":%u,\"synthetic_large\":%u,\"synthetic_eapol\":%u,\"wire_bytes\":%u,"
  "\"prom_cb_total\":%u,\"prom_data\":%u,\"prom_mgmt\":%u,\"prom_ctrl\":%u,\"prom_misc\":%u,\"prom_target_related_data\":%u,\"pair_seen\":%u,\"pair_frames\":%u,"
  "\"hs_up_seen\":%u,\"hs_down_seen\":%u,\"hs_up_protected\":%u,\"hs_down_protected\":%u,\"hs_up_clear_small\":%u,\"hs_down_clear_small\":%u,"
   "\"hs_pair_protected\":%u,\"hs_pair_unprotected\":%u,\"hs_pair_len_le256\":%u,\"hs_pair_len_gt256\":%u,\"hs_pair_small_accepted\":%u,"
   "\"hs_llc_snap_candidate\":%u,\"hs_ethertype_888e_candidate\":%u,"
  "\"hs_filter_protected\":%u,\"hs_filter_oversize\":%u,\"hs_filter_pair_mismatch\":%u,\"hs_filter_other\":%u,"
 "\"csi_cb_total\":%u,\"csi_null\":%u,\"csi_source_target\":%u,\"csi_source_other\":%u,\"csi_hdr_present\":%u,\"csi_buf_present\":%u,\"csi_valid_channel_estimate\":%u,\"csi_rxstate_ok\":%u,\"csi_target_valid\":%u,"
  "\"diag_pair_seen\":%u,\"diag_uplink\":%u,\"diag_downlink\":%u,\"diag_protected\":%u,\"diag_clear\":%u,\"diag_len_le256\":%u,\"diag_len_gt256\":%u,\"diag_llc_snap\":%u,\"diag_ethertype_888e\":%u,\"diag_candidate_enqueued\":%u,\"diag_reject_layout\":%u,\"diag_reject_length\":%u,\"diag_reject_protected\":%u,\"diag_reject_llc\":%u,\"diag_reject_ethertype\":%u,\"diag_invalid_csi\":%u,"
 "\"rx_11b\":%u,\"rx_legacy\":%u,\"rx_ht\":%u,\"rx_vht\":%u,\"rx_other\":%u,"
 "\"actual_channel\":%u,\"actual_mode\":%u,\"channel_readback_ok\":%s}",
 kind==7?control_event:kind==FINAL?"FINAL":"STATS",mode_name(),U(mode_epoch),synthetic_only?"true":"false",rf_capture_enabled?"true":"false",
 U(target_csi_seen),U(candidate_seen),U(csi_enqueued),U(csi_output),U(large_frame_filtered),U(filter_other),U(handshake_data_count),
 U(raw_drop)+U(csi_drop),U(csi_total),U(target_csi),U(raw_drop),U(csi_drop),U(raw_enqueued),U(csi_enqueued),U(raw_output),U(csi_output),U(eapol_frames),
 U(raw_truncated),U(csi_truncated),U(payload_truncated),U(payload_missing),U(csi_empty),U(hdr_conflict),U(write_errors),U(high_water),
 (unsigned)esp_get_free_heap_size(),(unsigned)esp_get_minimum_free_heap_size(),DEPTH,(unsigned)uxQueueMessagesWaiting(events),CANDIDATE_MAX,channel,synth_rate,synth_seconds,U(synthetic_candidates),U(synthetic_large),U(synthetic_eapol),U(wire_bytes),
  U(prom_total),U(prom_data_all),U(prom_mgmt_all),U(prom_ctrl_all),U(prom_misc_all),U(prom_target_related_data),U(pair_seen),U(pair_frames),
  U(hs_up_seen),U(hs_down_seen),U(hs_up_protected),U(hs_down_protected),U(hs_up_clear_small),U(hs_down_clear_small),
   U(hs_pair_protected),U(hs_pair_unprotected),U(hs_pair_len_le256),U(hs_pair_len_gt256),U(hs_pair_small_accepted),
   U(hs_llc_snap_candidate),U(hs_ethertype_888e_candidate),
  U(hs_filter_protected),U(hs_filter_oversize),U(hs_filter_pair_mismatch),U(hs_filter_other),
 U(csi_cb_total),U(csi_null),U(csi_source_target),U(csi_source_other),U(csi_hdr_present),U(csi_buf_present),U(csi_valid_channel_estimate),U(csi_rxstate_ok),U(csi_target_valid),
  U(diag_pair_seen),U(diag_uplink),U(diag_downlink),U(diag_protected),U(diag_clear),U(diag_len_le256),U(diag_len_gt256),U(diag_llc_snap),U(diag_ethertype_888e),U(diag_candidate_enqueued),U(diag_reject_layout),U(diag_reject_length),U(diag_reject_protected),U(diag_reject_llc),U(diag_reject_ethertype),U(diag_invalid_csi),
 U(rx_11b),U(rx_legacy),U(rx_ht),U(rx_vht),U(rx_other),
 (unsigned)actual_chan,(unsigned)actual_mode,channel_readback_ok?"true":"false");
 configASSERT(n>0&&n<CAP);put16(e.header+34,n);put16(e.header+36,n);put64(e.header+16,esp_timer_get_time());emit(&e);
 xSemaphoreGiveRecursive(tx_mutex);
}
static void output_task(void *arg){
 (void)arg;int64_t last=esp_timer_get_time();
 for(;;){event_t*e=NULL;if(xQueueReceive(events,&e,pdMS_TO_TICKS(10))==pdTRUE){emit(e);configASSERT(xQueueSend(free_slots,&e,0)==pdTRUE);}
  uint64_t now=esp_timer_get_time();unsigned mode=atomic_load(&capture_mode);
  if(mode==MODE_HANDSHAKE_DUAL_DIAG)timeline_flush(now,false);
  if(mode!=MODE_STOP&&now-(uint64_t)last>=1000000){control(STATS);if(mode==MODE_HANDSHAKE_DUAL_DIAG)dual_stats(now);if(mode==MODE_OPEN_AP_POC)open_ap_stats_control("OPEN_AP_STATS");last=(int64_t)now;}
 }
}
static void drain(void){
 while(uxQueueMessagesWaiting(free_slots)!=DEPTH)vTaskDelay(1);
 xSemaphoreTakeRecursive(tx_mutex,portMAX_DELAY);uart_wait_tx_done(UART_NUM_0,pdMS_TO_TICKS(5000));xSemaphoreGiveRecursive(tx_mutex);
}
static unsigned first_set(const void *v) {
    const uint8_t *p=v;for(unsigned i=0;i<sizeof(wifi_pkt_rx_ctrl_t);i++)if(p[i])return i;
    return UINT_MAX;
}
_Static_assert(offsetof(wifi_promiscuous_pkt_t,payload)==sizeof(wifi_pkt_rx_ctrl_t),"RX prefix ABI mismatch");
