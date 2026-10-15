// Independent ESP32-C5 passive CSI PoC. No AP association, scan, IP traffic or payload export.
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdatomic.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_wifi.h"
#include "esp_mac.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "driver/uart.h"
#include "esp_vfs_dev.h"

#define CSI_CAP 2048
#define DEPTH 32
#define PROBE_HEADER_LEN 28
#define PROBE_PAYLOAD_LEN 16
#define PROBE_TRAILER_LEN 4
#define PROBE_STATUS_NONE 0
#define PROBE_STATUS_PROTECTED 1
#define PROBE_STATUS_NO_MATCH 2
#define PROBE_STATUS_INVALID 3
#define PROBE_STATUS_VALID 4
static uint8_t target_mac[6];
static QueueHandle_t queue;
static volatile bool running = true;
static atomic_uint prom_parsed_ta, prom_mgmt_all, prom_data_all, prom_ctrl_all, prom_misc_all, frame_target_drop;
static atomic_uint prom_total, prom_target, prom_target_data, prom_target_mgmt, prom_target_ctrl;
static atomic_uint csi_total, csi_target, csi_target_valid, csi_target_data, csi_target_data_valid;
static atomic_uint frame_drop, csi_drop, csi_target_drop, csi_empty, csi_truncated;
static atomic_uint csi_target_hdr_conflict;
static atomic_uint prom_target_data_protected, prom_target_data_probe;
static atomic_uint csi_target_data_protected, csi_target_data_probe;
static uint8_t listen_channel;

typedef struct {
    uint8_t kind, target, ta_present, ra[6], ta[6], source[6];
    uint16_t fc, seq_ctrl, rx_seq, len, copied;
    uint8_t fc_protected, probe_status;
    uint32_t probe_run_id, probe_packet_id;
    uint64_t probe_sender_mono_ns;
    wifi_pkt_rx_ctrl_t meta;
    uint8_t valid, first_invalid;
    int8_t data[CSI_CAP];
} event_t;

typedef struct {
    uint8_t status;
    uint32_t run_id, packet_id;
    uint64_t sender_mono_ns;
} probe_result_t;

static bool match(const uint8_t *mac) { return memcmp(mac, target_mac, 6) == 0; }
// Address 2 is TA for ordinary data/management and selected control types.
// ACK/CTS carry only RA and must never be attributed to their receiver as TX.
static bool parse_header(event_t *e, const uint8_t *h, unsigned bytes) {
    if (!h || bytes < 10) return false;
    e->fc = (uint16_t)h[0] | ((uint16_t)h[1] << 8);
    unsigned type = (e->fc >> 2) & 3, sub = (e->fc >> 4) & 15;
    memcpy(e->ra, h + 4, 6);
    if (((type == 0 || type == 2) && bytes >= 24) ||
        (type == 1 && bytes >= 16 && (sub == 8 || sub == 9 || sub == 10 || sub == 11 || sub == 14 || sub == 15))) {
        memcpy(e->ta, h + 10, 6);
        e->ta_present = 1;
        if (type == 0 || type == 2) e->seq_ctrl = h[22] | (h[23] << 8);
    }
    return e->ta_present;
}

static uint16_t read_le16(const uint8_t *p) { return (uint16_t)p[0] | ((uint16_t)p[1] << 8); }
static uint32_t read_le32(const uint8_t *p) { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }
static uint64_t read_le64(const uint8_t *p) { return (uint64_t)read_le32(p) | ((uint64_t)read_le32(p + 4) << 32); }
static uint16_t read_be16(const uint8_t *p) { return ((uint16_t)p[0] << 8) | (uint16_t)p[1]; }

static uint32_t crc32_ieee(const uint8_t *data, unsigned len) {
    uint32_t crc = 0xffffffffu;
    for (unsigned i = 0; i < len; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}

static unsigned data_header_len(uint16_t fc) {
    if (((fc >> 2) & 3u) != 2u) return 0;
    unsigned sub = (fc >> 4) & 15u;
    unsigned len = 24;
    if (((fc >> 8) & 1u) && ((fc >> 9) & 1u)) len += 6; // Address 4
    if (sub & 8u) {
        len += 2; // QoS control
        if (fc & 0x8000u) len += 4; // HT control when present
    }
    return len;
}

static probe_result_t inspect_app_payload(const uint8_t *app, unsigned app_len) {
    probe_result_t result = { .status = PROBE_STATUS_NO_MATCH };
    static const uint8_t magic[4] = {'C','S','I','D'};
    if (!app || app_len < sizeof(magic) || memcmp(app, magic, sizeof(magic)) != 0) return result;
    result.status = PROBE_STATUS_INVALID;
    if (app_len < PROBE_HEADER_LEN + PROBE_TRAILER_LEN) return result;
    uint8_t version = app[4], header_len = app[5];
    uint16_t flags = read_le16(app + 6);
    uint32_t run_id = read_le32(app + 8), packet_id = read_le32(app + 12);
    uint64_t sender_mono_ns = read_le64(app + 16);
    uint16_t payload_len = read_le16(app + 24), reserved = read_le16(app + 26);
    unsigned expected_len = (unsigned)header_len + payload_len + PROBE_TRAILER_LEN;
    if (version != 1 || header_len != PROBE_HEADER_LEN || flags != 0 || reserved != 0 ||
        payload_len != PROBE_PAYLOAD_LEN || expected_len != app_len) return result;
    if (read_le32(app + app_len - PROBE_TRAILER_LEN) != crc32_ieee(app, app_len - PROBE_TRAILER_LEN)) return result;
    for (unsigned i = 0; i < payload_len; ++i) {
        if (app[header_len + i] != (uint8_t)(packet_id + i)) return result;
    }
    result.status = PROBE_STATUS_VALID;
    result.run_id = run_id;
    result.packet_id = packet_id;
    result.sender_mono_ns = sender_mono_ns;
    return result;
}

// The test application payload is visible only in unprotected 802.11 frames.
// Do not export frame bytes: record only a validated ID or the protected flag.
static probe_result_t inspect_wifi_body(const uint8_t *body, unsigned body_len, bool protected_frame) {
    probe_result_t result = { .status = PROBE_STATUS_NO_MATCH };
    if (protected_frame) { result.status = PROBE_STATUS_PROTECTED; return result; }
    if (!body || body_len < 8 + 20 || body[0] != 0xaa || body[1] != 0xaa || body[2] != 0x03 ||
        body[3] != 0x00 || body[4] != 0x00 || body[5] != 0x00 || read_be16(body + 6) != 0x0800) return result;
    const uint8_t *ip = body + 8;
    unsigned avail = body_len - 8;
    if ((ip[0] >> 4) != 4) return result;
    unsigned ihl = (ip[0] & 15u) * 4u;
    unsigned total_len = read_be16(ip + 2);
    if (ihl < 20 || ihl > avail || total_len < ihl + 8 || total_len > avail || ip[9] != 17) return result;
    uint16_t frag = read_be16(ip + 6);
    if (frag & 0x3fffu) return result; // no IPv4 fragmentation in this small-packet experiment
    const uint8_t *udp = ip + ihl;
    unsigned udp_len = read_be16(udp + 4);
    if (udp_len < 8 || udp_len != total_len - ihl) return result;
    return inspect_app_payload(udp + 8, udp_len - 8);
}

static void set_probe_fields(event_t *e, probe_result_t probe) {
    e->probe_status = probe.status;
    e->probe_run_id = probe.run_id;
    e->probe_packet_id = probe.packet_id;
    e->probe_sender_mono_ns = probe.sender_mono_ns;
}

static void prom_cb(void *buf, wifi_promiscuous_pkt_type_t kind) {
    if (!buf) return;
    atomic_fetch_add(&prom_total, 1);
    if (kind == WIFI_PKT_MISC) { atomic_fetch_add(&prom_misc_all, 1); return; } // MIMO/misc may have no payload: do not dereference it.
    if (kind == WIFI_PKT_MGMT) atomic_fetch_add(&prom_mgmt_all, 1);
    if (kind == WIFI_PKT_CTRL) atomic_fetch_add(&prom_ctrl_all, 1);
    if (kind == WIFI_PKT_DATA) atomic_fetch_add(&prom_data_all, 1);
    const wifi_promiscuous_pkt_t *p = buf;
    static event_t e;
    memset(&e, 0, sizeof(e));
    e.kind = 0;
    e.meta = p->rx_ctrl;
    // Use actual dumped length, never assume sig_len bytes of MIMO payload exist.
    if (!parse_header(&e, p->payload, p->rx_ctrl.dump_len)) return;
    atomic_fetch_add(&prom_parsed_ta, 1);
    e.target = match(e.ta);
    if (!e.target) return; // Count all callbacks; no background UART export.
    atomic_fetch_add(&prom_target, 1);
    unsigned type = (e.fc >> 2) & 3;
    if (type == 2) atomic_fetch_add(&prom_target_data, 1);
    if (type == 0) atomic_fetch_add(&prom_target_mgmt, 1);
    if (type == 1) atomic_fetch_add(&prom_target_ctrl, 1);
    if (type != 2) return; // Management/control counted above, never queued.
    e.fc_protected = (e.fc >> 14) & 1u;
    unsigned hdr_len = data_header_len(e.fc);
    probe_result_t probe = { .status = e.fc_protected ? PROBE_STATUS_PROTECTED : PROBE_STATUS_NO_MATCH };
    if (!e.fc_protected && hdr_len && hdr_len <= p->rx_ctrl.dump_len)
        probe = inspect_wifi_body(p->payload + hdr_len, p->rx_ctrl.dump_len - hdr_len, false);
    set_probe_fields(&e, probe);
    if (probe.status == PROBE_STATUS_PROTECTED) atomic_fetch_add(&prom_target_data_protected, 1);
    if (probe.status == PROBE_STATUS_VALID) atomic_fetch_add(&prom_target_data_probe, 1);
    if (xQueueSend(queue, &e, 0) != pdTRUE) { atomic_fetch_add(&frame_drop, 1); atomic_fetch_add(&frame_target_drop,1); }
}
static void csi_cb(void *ctx, wifi_csi_info_t *p) {
    (void)ctx;
    atomic_fetch_add(&csi_total, 1);
    if (!p) { atomic_fetch_add(&csi_empty, 1); return; }
    bool target = match(p->mac);
    if (target) atomic_fetch_add(&csi_target, 1);
    bool valid = p->rx_ctrl.rx_channel_estimate_info_vld && p->rx_ctrl.rx_state == 0 && p->buf && p->len > 0;
    if (target && valid) atomic_fetch_add(&csi_target_valid, 1);
    static event_t e;
    memset(&e, 0, sizeof(e));
    e.kind = 1; e.target = target;
    e.meta = p->rx_ctrl; e.valid = p->rx_ctrl.rx_channel_estimate_info_vld;
    e.first_invalid = p->first_word_invalid; e.rx_seq = p->rx_seq;
    memcpy(e.source, p->mac, 6); memcpy(e.ra, p->dmac, 6);
    if (parse_header(&e, p->hdr, p->rx_ctrl.dump_len)) {
        if (target && !match(e.ta)) atomic_fetch_add(&csi_target_hdr_conflict, 1);
        if (target && match(e.ta) && ((e.fc >> 2) & 3) == 2) {
            atomic_fetch_add(&csi_target_data, 1);
            if (valid) atomic_fetch_add(&csi_target_data_valid, 1);
            e.fc_protected = (e.fc >> 14) & 1u;
            probe_result_t probe = inspect_wifi_body(p->payload, p->payload_len, e.fc_protected != 0);
            set_probe_fields(&e, probe);
            if (probe.status == PROBE_STATUS_PROTECTED) atomic_fetch_add(&csi_target_data_protected, 1);
            if (probe.status == PROBE_STATUS_VALID) atomic_fetch_add(&csi_target_data_probe, 1);
        }
    }
    if (!p->buf || !p->len) atomic_fetch_add(&csi_empty, 1);
    // Preserve all counts above. Queue only source/header-confirmed valid Data CSI.
    if (!target || !e.ta_present || !match(e.ta) || ((e.fc >> 2) & 3) != 2 || !valid) return;
    e.len = p->len;
    if (p->buf) {
        e.copied = p->len > CSI_CAP ? CSI_CAP : p->len;
        if (p->len > CSI_CAP) atomic_fetch_add(&csi_truncated, 1);
        // Raw SDK bytes, no gain compensation or I/Q reinterpretation.
        memcpy(e.data, p->buf, e.copied);
    }
    // Control/background never enter the output queue.
    if (xQueueSend(queue, &e, 0) != pdTRUE) {
        atomic_fetch_add(&csi_drop, 1);
        if (target) atomic_fetch_add(&csi_target_drop, 1);
    }
}
#define U(v) ((unsigned)atomic_load(&(v)))
static void stats(const char *event) {
    printf("{\"event\":\"%s\",\"hostless_us\":%" PRId64 ",\"prom_total\":%u,\"prom_target\":%u,\"prom_target_data\":%u,\"prom_target_mgmt\":%u,\"prom_target_ctrl\":%u,\"csi_total\":%u,\"csi_target\":%u,\"csi_target_valid\":%u,\"csi_target_data\":%u,\"csi_target_data_valid\":%u,\"prom_target_data_protected\":%u,\"prom_target_data_probe\":%u,\"csi_target_data_protected\":%u,\"csi_target_data_probe\":%u,\"frame_drop\":%u,\"csi_drop\":%u,\"csi_target_drop\":%u,\"csi_empty\":%u,\"csi_truncated\":%u,\"csi_target_hdr_conflict\":%u,\"prom_parsed_ta\":%u,\"prom_mgmt_all\":%u,\"prom_data_all\":%u,\"prom_ctrl_all\":%u,\"prom_misc_all\":%u,\"frame_target_drop\":%u}\n",
        event, esp_timer_get_time(), U(prom_total),U(prom_target),U(prom_target_data),U(prom_target_mgmt),U(prom_target_ctrl),U(csi_total),U(csi_target),U(csi_target_valid),U(csi_target_data),U(csi_target_data_valid),U(prom_target_data_protected),U(prom_target_data_probe),U(csi_target_data_protected),U(csi_target_data_probe),U(frame_drop),U(csi_drop),U(csi_target_drop),U(csi_empty),U(csi_truncated),U(csi_target_hdr_conflict),U(prom_parsed_ta),U(prom_mgmt_all),U(prom_data_all),U(prom_ctrl_all),U(prom_misc_all),U(frame_target_drop));
}
static void print_event(const event_t *e) {
    printf("{\"event\":\"%s\",\"target\":%u,\"timestamp\":%u,\"rssi\":%d,\"channel\":%u,\"second\":%u,\"format\":%u,\"rate\":%u,\"sig_len\":%u,\"dump_len\":%u,\"rx_state\":%u,\"estimate_valid\":%u,\"estimate_len\":%u,\"he_siga1\":%" PRIu32 ",\"he_siga2\":%u,\"fc\":%u,\"frame_type\":%u,\"subtype\":%u,\"to_ds\":%u,\"from_ds\":%u,\"protected\":%u,\"app_probe_status\":%u,\"app_run_id\":%" PRIu32 ",\"app_packet_id\":%" PRIu32 ",\"app_sender_mono_ns\":%" PRIu64 ",\"seq_ctrl\":%u,\"ta_present\":%u,\"ta\":\"" MACSTR "\",\"ra\":\"" MACSTR "\",\"source\":\"" MACSTR "\",\"rx_seq\":%u,\"len\":%u,\"copied\":%u,\"first_word_invalid\":%u",
        e->kind ? "CSI" : "FRAME", e->target, (unsigned)e->meta.timestamp, e->meta.rssi, e->meta.channel, e->meta.second, e->meta.cur_bb_format, e->meta.rate, e->meta.sig_len, e->meta.dump_len, e->meta.rx_state, e->valid, e->meta.rx_channel_estimate_len, e->meta.he_siga1, e->meta.he_siga2,
        e->fc,(e->fc>>2)&3,(e->fc>>4)&15,(e->fc>>8)&1,(e->fc>>9)&1,e->fc_protected,e->probe_status,e->probe_run_id,e->probe_packet_id,e->probe_sender_mono_ns,e->seq_ctrl,e->ta_present,MAC2STR(e->ta),MAC2STR(e->ra),MAC2STR(e->source),e->rx_seq,e->len,e->copied,e->first_invalid);
    if (e->kind) {
        printf(",\"data_hex\":\"");
        for (unsigned i=0;i<e->copied;i++) printf("%02x",(uint8_t)e->data[i]);
        printf("\"");
    }
    printf("}\n");
}
static void output_task(void *arg) {
    (void)arg;
    event_t e;
    int64_t last = esp_timer_get_time();
    while (running || uxQueueMessagesWaiting(queue)) {
        if (xQueueReceive(queue, &e, pdMS_TO_TICKS(20)) == pdTRUE) print_event(&e);
        int64_t now = esp_timer_get_time();
        if (now-last >= 1000000) { stats("STATS"); last=now; }
    }
    stats("FINAL");
    vTaskDelete(NULL);
}
void app_main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 2048, 0, 0, NULL, 0));
    esp_vfs_dev_uart_use_driver(UART_NUM_0);
    printf("{\"event\":\"READY\",\"version\":\"sniffer-5-packet-id\",\"max_csi_bytes\":%d}\n",CSI_CAP);
    char line[128]; unsigned ch,m[6];
    for (;;) {
        if (fgets(line,sizeof(line),stdin) && sscanf(line,"CFG,%u,%x:%x:%x:%x:%x:%x",&ch,&m[0],&m[1],&m[2],&m[3],&m[4],&m[5])==7 && ch>0 && ch<200) {
            bool good=true;
            for (unsigned i=0;i<6;i++) if (m[i]>255) good=false;
            if (!good) continue;
            listen_channel=ch;
            for (unsigned i=0;i<6;i++) target_mac[i]=m[i];
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    ESP_ERROR_CHECK(nvs_flash_init()); // no erasure fallback: preserve unrelated NVS
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_NULL));
    ESP_ERROR_CHECK(esp_wifi_set_country_code("CN",false));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_band_mode(ch>14?WIFI_BAND_MODE_5G_ONLY:WIFI_BAND_MODE_2G_ONLY));
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    // WIFI_MODE_NULL has no STA interface: set_bandwidth(WIFI_IF_STA, ...) is invalid.
    // Keep passive NULL mode; report channel/secondary but do not claim measured RX bandwidth.
    queue=xQueueCreate(DEPTH,sizeof(event_t));
    configASSERT(queue);
    wifi_promiscuous_filter_t filter={.filter_mask=WIFI_PROMIS_FILTER_MASK_MGMT|WIFI_PROMIS_FILTER_MASK_DATA|WIFI_PROMIS_FILTER_MASK_CTRL|WIFI_PROMIS_FILTER_MASK_MISC};
    wifi_promiscuous_filter_t ctrl={.filter_mask=WIFI_PROMIS_CTRL_FILTER_MASK_ALL};
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_filter(&filter));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_ctrl_filter(&ctrl));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_rx_cb(prom_cb));
    ESP_ERROR_CHECK(esp_wifi_set_channel(listen_channel,WIFI_SECOND_CHAN_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
    wifi_csi_config_t csi={.enable=1,.acquire_csi_legacy=1,.acquire_csi_force_lltf=0,.acquire_csi_ht20=1,.acquire_csi_ht40=1,.acquire_csi_vht=1,.acquire_csi_su=1,.acquire_csi_mu=1,.acquire_csi_dcm=1,.acquire_csi_beamformed=1,.acquire_csi_he_stbc_mode=2,.val_scale_cfg=0,.dump_ack_en=0,.lltf_bit_mode=0};
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_cb,NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
    uint8_t actual=0;wifi_second_chan_t secondary=WIFI_SECOND_CHAN_NONE;
    ESP_ERROR_CHECK(esp_wifi_get_channel(&actual,&secondary));
    printf("{\"event\":\"ARMED\",\"channel\":%u,\"secondary\":%u,\"target\":\"" MACSTR "\",\"mode\":\"NULL\",\"rx_bw\":null,\"ack_csi\":false}\n",actual,secondary,MAC2STR(target_mac));
    configASSERT(xTaskCreate(output_task,"serial_output",6144,NULL,5,NULL)==pdPASS);
    for (;;) {
        if (fgets(line,sizeof(line),stdin) && strncmp(line,"STOP",4)==0) {
            ESP_ERROR_CHECK(esp_wifi_set_csi(false));
            ESP_ERROR_CHECK(esp_wifi_set_promiscuous(false));
            running=false;
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}
