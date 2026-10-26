"""Capture CSI-centric diagnostics from the ESP over UART only.

This tool never connects to or changes the Jetson/AP. Diagnostic modes stop only
when their local stop-file appears or the bounded maximum duration expires.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import serial

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'uart_benchmark/tools'))
from benchmark_host import connect
from wire8c import Decoder
from analyze_dual_diag import analyze_capture

FIRMWARE = 'sniffer-8d-csi-centric'
EXPECTED_MODE = {'PROBE': 'PROBE_CAPTURE', 'HANDSHAKE_DIAG': 'HANDSHAKE_DIAG',
                 'HANDSHAKE_DUAL_DIAG': 'HANDSHAKE_DUAL_DIAG'}
DIAGNOSTIC_MODES = ('HANDSHAKE_DIAG', 'HANDSHAKE_DUAL_DIAG')
ERRORS = ('bad_header', 'crc_error', 'discarded_bytes', 'serial_discontinuity',
          'raw_metadata_conflict', 'incomplete_bytes')


def passive_sanity_failures(summary):
    """Apply the physical passive-sanity gate to the final device counters."""
    if summary.get('mode') != 'PROBE':
        return []
    failures = []
    if summary.get('channel') != 2 or summary.get('actual_channel') != 2:
        failures.append('channel is not confirmed as 2')
    if summary.get('channel_readback_ok') is not True:
        failures.append('channel readback failed')
    if not summary.get('mode_ack') or not summary.get('stop_ack') or not summary.get('final_received'):
        failures.append('PROBE/STOP/FINAL control handshake incomplete')
    counters = summary.get('counters', {})
    if counters.get('csi_target_valid', counters.get('target_csi', 0)) <= 0:
        failures.append('target valid CSI is zero')
    for key in ('queue_drop', 'raw_drop', 'csi_drop', 'write_errors',
                'raw_truncated', 'csi_truncated', 'payload_truncated'):
        if counters.get(key, 0) != 0:
            failures.append(f'{key} is nonzero')
    transport = summary.get('transport_errors', {})
    for key, value in transport.items():
        if value:
            failures.append(f'transport/parser {key} is nonzero')
    return failures


def main():
    p = argparse.ArgumentParser(description='Bounded UART capture for CSI-centric PoCs')
    p.add_argument('--port', default='COM10')
    p.add_argument('--channel', type=int, default=2)
    p.add_argument('--target', required=True)
    p.add_argument('--ap', required=True)
    p.add_argument('--baud', type=int, default=3000000)
    p.add_argument('--mode', choices=('PROBE', 'HANDSHAKE_DIAG', 'HANDSHAKE_DUAL_DIAG'), default='PROBE')
    p.add_argument('--duration', type=float, default=12.0,
                   help='PROBE sanity duration; ignored by HANDSHAKE_DIAG')
    p.add_argument('--max-duration', type=float, default=300.0)
    p.add_argument('--stop-file', type=Path,
                   help='diagnostic mode ends after this local file is created')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()

    for m in (a.target, a.ap):
        if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', m):
            p.error('Invalid MAC format')
    if not 1 <= a.channel <= 196 or not 0 < a.baud <= 3000000:
        p.error('Invalid channel or baud')
    if a.mode == 'PROBE' and not 0 < a.duration <= 15:
        p.error('PROBE sanity duration must be 1..15 seconds')
    if a.mode in DIAGNOSTIC_MODES:
        if not a.stop_file:
            p.error(f'{a.mode} requires --stop-file')
        if a.stop_file.exists():
            p.error('stop-file already exists; choose a new path')
        if not 0 < a.max_duration <= 300:
            p.error('diagnostic max duration must be 1..300 seconds')

    a.target = a.target.lower()
    a.ap = a.ap.lower()
    a.output.mkdir(parents=True, exist_ok=False)
    decoder = Decoder()
    configured = False
    mode_ack = False
    final = None
    counters = {}
    cfg_counters = {}
    records = {'CSI_DATA': 0, 'FRAME': 0, 'TIMELINE': 0}
    timeline_rows = []
    stop_ack = False
    stop_reason = None

    s = serial.Serial(port=None, baudrate=921600, timeout=0.1)
    s.dtr = False
    s.rts = False
    s.port = a.port

    def send(command):
        s.write((command + '\n').encode('ascii'))

    def receive_chunk(raw, times):
        b = s.read(max(1, min(65536, s.in_waiting)))
        if not b:
            return
        raw.write(b)
        for row in decoder.feed(b):
            times.write(json.dumps(dict(record_serial=row['record_serial'],
                                        host_time_ns=time.time_ns(),
                                        host_mono_ns=time.monotonic_ns())) + '\n')
            if row['event'] in records:
                records[row['event']] += 1
            if row['event'] == 'TIMELINE':
                timeline_rows.append(dict(record_serial=row['record_serial'],
                                          host_time_ns=time.time_ns(),
                                          host_mono_ns=time.monotonic_ns(),
                                          counters=row.get('counters', {})))
            if row['event'] in ('CONTROL', 'STATS', 'FINAL'):
                counters.update(row.get('counters', {}))

    with s, (a.output / 'stream.bin').open('xb') as raw, \
            (a.output / 'stream.bin.times.jsonl').open('x', encoding='utf-8') as times:
        print(f'Connecting to {a.port}; expected firmware {FIRMWARE}', flush=True)
        ready, baud_ready = connect(s, FIRMWARE, a.baud)
        (a.output / 'ready.json').write_text(
            json.dumps(dict(ready=ready, baud=baud_ready), indent=2), encoding='utf-8')

        send(f'CFG,{a.channel},{a.target},{a.ap}')
        deadline = time.monotonic() + 10
        while not configured and time.monotonic() < deadline:
            receive_chunk(raw, times)
            if counters.get('event') == 'CONFIGURED':
                configured = True
                cfg_counters = dict(counters)
        if not configured:
            raise RuntimeError('Timed out waiting for CONFIGURED')
        if not cfg_counters.get('channel_readback_ok'):
            send('MODE STOP')
            raise RuntimeError('Configured channel readback did not match request')

        send('MODE ' + a.mode)
        expected_mode = EXPECTED_MODE[a.mode]
        deadline = time.monotonic() + 10
        while not mode_ack and time.monotonic() < deadline:
            receive_chunk(raw, times)
            if counters.get('event') == 'MODE_ACK' and counters.get('mode') == expected_mode:
                mode_ack = True
        if not mode_ack or not counters.get('rf_capture_enabled'):
            send('MODE STOP')
            raise RuntimeError('HANDSHAKE_DIAG/PROBE MODE_ACK failed')

        started = time.monotonic()
        if a.mode == 'PROBE':
            print(f'PASSIVE PROBE sanity armed on channel {a.channel} for {a.duration:.1f}s', flush=True)
        else:
            print(f'{a.mode} ARMED on channel {a.channel}; waiting for local stop-file '
                  f'or {a.max_duration:.0f}s timeout. Jetson is untouched.', flush=True)
        last_report = started
        while True:
            now = time.monotonic()
            elapsed = now - started
            if a.mode == 'PROBE' and elapsed >= a.duration:
                stop_reason = 'duration'
                break
            if a.mode in DIAGNOSTIC_MODES and a.stop_file.exists():
                stop_reason = 'stop_file'
                break
            if a.mode in DIAGNOSTIC_MODES and elapsed >= a.max_duration:
                stop_reason = 'max_duration'
                break
            receive_chunk(raw, times)
            if now - last_report >= 5:
                last_report = now
                print(f'[{elapsed:5.1f}s] csi_cb={counters.get("csi_cb_total", 0)} '
                      f'target_valid={counters.get("csi_target_valid", 0)} '
                      f'dual_csi_pair={counters.get("csi_pair", counters.get("diag_pair_seen", 0))} '
                      f'dual_prom_pair={counters.get("prom_pair", 0)} '
                      f'CSI_DATA={records["CSI_DATA"]} '
                      f'queue_drop={counters.get("queue_drop", 0)} '
                      f'write_errors={counters.get("write_errors", 0)}', flush=True)

        send('MODE STOP')
        deadline = time.monotonic() + 15
        while final is None and time.monotonic() < deadline:
            receive_chunk(raw, times)
            if counters.get('event') == 'MODE_ACK' and counters.get('mode') == 'STOP':
                stop_ack = True
            # MODE STOP also emits an explicit FINAL record.
            if decoder.counts.get('FINAL', 0):
                final = True
        raw.flush()
        times.flush()

    (a.output / 'timeline.jsonl').write_text(
        ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in timeline_rows), encoding='utf-8')

    health = decoder.finish()
    summary = dict(firmware=FIRMWARE, mode=a.mode, channel=a.channel,
                   duration_s=round(time.monotonic() - started, 3), stop_reason=stop_reason,
                   channel_readback_ok=cfg_counters.get('channel_readback_ok'),
                   actual_channel=cfg_counters.get('actual_channel'),
                   mode_ack=mode_ack, stop_ack=stop_ack, final_received=bool(final),
                   records=records, counters=counters, transport=health,
                   transport_errors={k: health.get(k, 0) for k in ERRORS})
    sanity_failures = passive_sanity_failures(summary)
    summary['sanity_failures'] = sanity_failures
    (a.output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    analysis_error = None
    if a.mode == 'HANDSHAKE_DUAL_DIAG' and final and stop_ack and not any(health.get(k, 0) for k in ERRORS):
        try:
            analysis = analyze_capture(a.output, a.target, a.ap)
            summary['analysis'] = dict(summary_json='dual_diag_summary.json',
                                       report='dual_diag_report.md',
                                       private_pcap='analysis_private/combined_private.pcap',
                                       handshake=analysis['handshake'],
                                       csi_data=analysis['csi_data'])
        except Exception as exc:  # Keep raw evidence and make analysis failure explicit.
            analysis_error = f'{type(exc).__name__}: {exc}'
            summary['analysis_error'] = analysis_error
            (a.output / 'analysis_error.txt').write_text(analysis_error + '\n', encoding='utf-8')
        (a.output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(dict(mode=a.mode, stop_reason=stop_reason, records=records,
                          csi_cb=counters.get('csi_cb_total'),
                          target_valid=counters.get('csi_target_valid'),
                          diag_pair_seen=counters.get('diag_pair_seen'),
                          stop_ack=stop_ack, final_received=bool(final),
                          sanity_failures=sanity_failures,
                          analysis_error=analysis_error,
                          transport=health), indent=2), flush=True)
    if sanity_failures:
        return 3
    if not final or not stop_ack or any(health.get(k, 0) for k in ERRORS):
        return 2
    return 4 if analysis_error else 0


if __name__ == '__main__':
    raise SystemExit(main())
