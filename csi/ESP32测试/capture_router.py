import argparse, csv, json, time
from collections import Counter
from pathlib import Path
import serial

ap = argparse.ArgumentParser()
ap.add_argument('--port', default='COM10')
ap.add_argument('--baud', type=int, default=921600)
ap.add_argument('--seconds', type=int, default=300)
ap.add_argument('--out', required=True)
a = ap.parse_args()
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
s = serial.Serial(port=None, baudrate=a.baud, timeout=0.5)
s.dtr = False
s.rts = False
s.port = a.port
s.open()
s.rts = True
time.sleep(0.1)
s.rts = False
start = time.monotonic()
last = start
counts = Counter()
lens, macs, channels = Counter(), Counter(), Counter()
first_words = Counter()
seq_first = seq_last = None
with (out/'serial_raw.log').open('w', encoding='utf-8') as f:
    try:
        while time.monotonic() - start < a.seconds:
            line = s.readline().decode('utf-8', errors='replace').rstrip()
            if line:
                f.write(line+'\n')
                counts['serial_lines'] += 1
                if 'CSI_DATA,' in line:
                    try:
                        row = next(csv.reader([line[line.index('CSI_DATA,'):]]))
                        values = json.loads(row[14])
                        n = int(row[12])
                        counts['csi_records'] += 1
                        counts['length_matches_array' if n == len(values) else 'length_mismatch'] += 1
                        lens[n] += 1
                        macs[row[2]] += 1
                        channels[row[8]] += 1
                        first_words[row[13]] += 1
                        seq_last = int(row[1])
                        if seq_first is None: seq_first = seq_last
                    except (ValueError, IndexError, StopIteration):
                        counts['parse_errors'] += 1
                elif any(t in line for t in ['Connecting to', 'connected with', 'got ip', 'Got IPv4', 'Error', 'assert', 'abort', 'disconnect', 'CSI RECV', 'Project name', 'App version']):
                    print(line, flush=True)
            now = time.monotonic()
            if now-last >= 30:
                f.flush()
                print(json.dumps({'elapsed_s':round(now-start), **counts}), flush=True)
                last = now
    finally:
        s.close()
result = {'duration_s':round(time.monotonic()-start,2), 'port':a.port, 'baud':a.baud, 'counts':dict(counts), 'lengths':dict(lens), 'source_macs':dict(macs), 'channels':dict(channels), 'first_word_invalid':dict(first_words), 'seq_first':seq_first, 'seq_last':seq_last, 'valid_field':'not_exported_by_upstream', 'scope':'AP-to-ESP router baseline; no packet_id association'}
(out/'capture_summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result,ensure_ascii=False),flush=True)
