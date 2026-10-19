"""Dedicated 8d-a passive capture tool.
Controls ESP UART only, never touches Jetson network or initiates reassociation.
Verifies firmware version sniffer-8d-a-full-filter and records all observational counters.
"""
import argparse, json, re, sys, time
from pathlib import Path
import serial

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'uart_benchmark/tools'))
from benchmark_host import connect
from wire8c import Decoder

ERRORS = ('queue_drop', 'raw_drop', 'csi_drop', 'raw_truncated', 'csi_truncated', 
          'payload_truncated', 'payload_missing', 'csi_empty', 'hdr_conflict', 'write_errors')

def main():
    p = argparse.ArgumentParser(description="8d-a passive RF capture")
    p.add_argument('--port', default='COM10')
    p.add_argument('--channel', type=int, default=2)
    p.add_argument('--target', required=True)
    p.add_argument('--ap', required=True)
    p.add_argument('--baud', type=int, default=3000000)
    p.add_argument('--duration', type=float, default=30.0)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()

    for m in (a.target, a.ap):
        if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', m):
            p.error('Invalid MAC format')
    if not 1 <= a.channel <= 196 or not 0 < a.duration <= 600:
        p.error('Invalid channel/duration')

    a.target = a.target.lower()
    a.ap = a.ap.lower()
    a.output.mkdir(parents=True, exist_ok=False)

    d = Decoder()
    ready = br = final = None
    counters = {}
    cfg_counters = {}
    configured = False
    mode_ack_received = False
    stop_ack_received = False
    stop_sent = False
    csi_data_count = 0
    frame_count = 0
    control_records = []
    
    s = serial.Serial(port=None, baudrate=921600, timeout=0.1)
    s.dtr = False
    s.rts = False
    s.port = a.port

    def send(cmd):
        s.write((cmd + '\n').encode())

    with s, (a.output / 'stream.bin').open('xb') as raw, (a.output / 'stream.bin.times.jsonl').open('x', encoding='utf-8') as times:
        print(f"Connecting to ESP on {a.port} with target version sniffer-8d-a-full-filter...", flush=True)
        ready, br = connect(s, 'sniffer-8d-a-full-filter', a.baud)
        print(f"Connected! Firmware: {ready['version']}, Baud: {br['actual']}", flush=True)
        (a.output / 'ready.json').write_text(json.dumps(dict(ready=ready, baud=br), indent=2), encoding='utf-8')

        # Send CFG
        send(f'CFG,{a.channel},{a.target},{a.ap}')
        setup_deadline = time.monotonic() + 10
        while not configured:
            now = time.monotonic()
            if now > setup_deadline:
                raise RuntimeError("Timeout waiting for CONFIGURED response")
            b = s.read(max(1, min(65536, s.in_waiting)))
            if b:
                raw.write(b)
                for r in d.feed(b):
                    times.write(json.dumps(dict(record_serial=r['record_serial'], host_time_ns=time.time_ns(), host_mono_ns=time.monotonic_ns())) + '\n')
                    if r['event'] == 'CONTROL' and r.get('counters', {}).get('event') == 'CONFIGURED':
                        configured = True
                        cfg_counters = r['counters']
                        print(f"CONFIGURED acknowledged. Readback channel: {cfg_counters.get('actual_channel')}, mode: {cfg_counters.get('actual_mode')}, ok: {cfg_counters.get('channel_readback_ok')}", flush=True)

        if not cfg_counters.get('channel_readback_ok'):
            send('MODE STOP')
            raise RuntimeError(f"Channel readback error! configured={a.channel}, actual={cfg_counters.get('actual_channel')}")

        # Send MODE PROBE
        print("Entering MODE PROBE for passive listening...", flush=True)
        send('MODE PROBE')
        mode_deadline = time.monotonic() + 10
        while not mode_ack_received:
            now = time.monotonic()
            if now > mode_deadline:
                raise RuntimeError("Timeout waiting for MODE_ACK")
            b = s.read(max(1, min(65536, s.in_waiting)))
            if b:
                raw.write(b)
                for r in d.feed(b):
                    times.write(json.dumps(dict(record_serial=r['record_serial'], host_time_ns=time.time_ns(), host_mono_ns=time.monotonic_ns())) + '\n')
                    if r['event'] == 'CONTROL' and r.get('counters', {}).get('event') == 'MODE_ACK':
                        mode_ack_received = True
                        print(f"MODE_ACK received! rf_capture_enabled: {r['counters'].get('rf_capture_enabled')}", flush=True)

        # Passive observation loop
        capture_start = time.monotonic()
        print(f"Passive listening started for {a.duration} seconds. Jetson is untouched...", flush=True)
        last_log = time.monotonic()
        while time.monotonic() - capture_start < a.duration:
            b = s.read(max(1, min(65536, s.in_waiting)))
            if b:
                raw.write(b)
                for r in d.feed(b):
                    times.write(json.dumps(dict(record_serial=r['record_serial'], host_time_ns=time.time_ns(), host_mono_ns=time.monotonic_ns())) + '\n')
                    if r['event'] == 'CSI_DATA':
                        csi_data_count += 1
                    elif r['event'] == 'FRAME':
                        frame_count += 1
                    elif r['event'] == 'CONTROL':
                        control_records.append(r)
                        counters = r.get('counters', {})
            now = time.monotonic()
            if now - last_log >= 5.0:
                last_log = now
                elapsed = now - capture_start
                print(f"[{elapsed:4.1f}s] prom_total={counters.get('prom_cb_total',0)}, csi_total={counters.get('csi_cb_total',0)}, target_csi={counters.get('csi_target_valid',0)}, csi_records={csi_data_count}", flush=True)

        # Stop mode
        print("Duration reached. Stopping capture...", flush=True)
        send('MODE STOP')
        stop_sent = True
        stop_deadline = time.monotonic() + 15
        while not final:
            now = time.monotonic()
            if now > stop_deadline:
                print("Warning: timeout waiting for FINAL", flush=True)
                break
            b = s.read(max(1, min(65536, s.in_waiting)))
            if b:
                raw.write(b)
                for r in d.feed(b):
                    times.write(json.dumps(dict(record_serial=r['record_serial'], host_time_ns=time.time_ns(), host_mono_ns=time.monotonic_ns())) + '\n')
                    if r['event'] == 'CONTROL':
                        control_records.append(r)
                        counters = r.get('counters', {})
                        if counters.get('event') == 'MODE_ACK' and counters.get('mode') == 'STOP':
                            stop_ack_received = True
                    elif r['event'] == 'FINAL':
                        final = r
                        print("FINAL received successfully.", flush=True)

    # Compute transport summary
    transport_counts = dict(d.counts)
    summary = {
        "version": "sniffer-8d-a-full-filter",
        "duration_requested_s": a.duration,
        "channel": a.channel,
        "rf_state": {
            "actual_channel": counters.get("actual_channel"),
            "actual_mode": counters.get("actual_mode"),
            "channel_readback_ok": counters.get("channel_readback_ok"),
            "rf_capture_enabled": counters.get("rf_capture_enabled"),
            "mode": counters.get("mode")
        },
        "promiscuous": {
            "prom_cb_total": counters.get("prom_cb_total", 0),
            "prom_mgmt": counters.get("prom_mgmt", 0),
            "prom_ctrl": counters.get("prom_ctrl", 0),
            "prom_data": counters.get("prom_data", 0),
            "prom_misc": counters.get("prom_misc", 0)
        },
        "csi_pipeline": {
            "csi_cb_total": counters.get("csi_cb_total", 0),
            "csi_null": counters.get("csi_null", 0),
            "csi_source_target": counters.get("csi_source_target", 0),
            "csi_source_other": counters.get("csi_source_other", 0),
            "csi_hdr_present": counters.get("csi_hdr_present", 0),
            "csi_buf_present": counters.get("csi_buf_present", 0),
            "csi_valid_channel_estimate": counters.get("csi_valid_channel_estimate", 0),
            "csi_rxstate_ok": counters.get("csi_rxstate_ok", 0),
            "csi_target_valid": counters.get("csi_target_valid", 0),
            "csi_data_records_exported": csi_data_count
        },
        "phy_distribution": {
            "rx_11b": counters.get("rx_11b", 0),
            "rx_legacy": counters.get("rx_legacy", 0),
            "rx_ht": counters.get("rx_ht", 0),
            "rx_vht": counters.get("rx_vht", 0),
            "rx_other": counters.get("rx_other", 0)
        },
        "candidate_filter": {
            "candidate_seen": counters.get("candidate_seen", 0),
            "candidate_enqueued": counters.get("candidate_enqueued", 0),
            "candidate_output": counters.get("candidate_output", 0),
            "large_frame_filtered": counters.get("large_frame_filtered", 0),
            "filter_other": counters.get("filter_other", 0),
            "handshake_data_count": counters.get("handshake_data_count", 0)
        },
        "resources": {
            "queue_drop": counters.get("queue_drop", 0),
            "write_errors": counters.get("write_errors", 0),
            "high_water": counters.get("high_water", 0),
            "queue_depth": counters.get("queue_depth", 0),
            "free_heap": counters.get("free_heap", 0),
            "min_free_heap": counters.get("min_free_heap", 0),
            "raw_truncated": counters.get("raw_truncated", 0),
            "csi_truncated": counters.get("csi_truncated", 0),
            "payload_truncated": counters.get("payload_truncated", 0),
            "payload_missing": counters.get("payload_missing", 0),
            "csi_empty": counters.get("csi_empty", 0),
            "hdr_conflict": counters.get("hdr_conflict", 0)
        },
        "transport": transport_counts,
        "stop_ack_received": stop_ack_received,
        "final_received": bool(final)
    }

    summary_file = a.output / 'summary.json'
    summary_file.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(f"\nSummary successfully written to {summary_file}")
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
