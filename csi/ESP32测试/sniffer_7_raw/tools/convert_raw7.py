"""Convert a saved CS7R binary stream to local JSONL, PCAP and metadata sidecar."""
import argparse
import json
from pathlib import Path
from raw7 import Decoder, join, write_pcap


def convert(source, out):
    out.mkdir(parents=True,exist_ok=False)
    d=Decoder();rows=[]
    with source.open('rb') as f:
        while data:=f.read(65536):rows.extend(d.feed(data))
    audit=d.finish()
    # Offline conversion must not invent host timestamps or silently ignore transport damage.
    bad=any(audit.get(k,0) for k in ('discarded_bytes','bad_header','crc_error','serial_discontinuity','incomplete_bytes','raw_metadata_conflict'))
    # Capture companion timing file maps every serial to host wall and monotonic time.
    timing=source.with_suffix(source.suffix+'.times.jsonl')
    if timing.exists():
        times={r['record_serial']:r for r in map(json.loads,timing.read_text(encoding='utf-8').splitlines())}
        for r in rows:r.update({k:times[r['record_serial']][k] for k in ('host_time_ns','host_mono_ns')})
        if not bad:
            index=write_pcap(rows,out/'frames.pcap')
            (out/'frame_index.json').write_text(json.dumps(index,indent=2),encoding='utf-8')
    with (out/'records.jsonl').open('x',encoding='utf-8') as f:
        for r in rows:f.write(json.dumps(r,separators=(',',':'))+'\n')
    (out/'joins.json').write_text(json.dumps(join(rows),indent=2),encoding='utf-8')
    audit['transport_passed']=not bad;audit['pcap_written']=(out/'frames.pcap').exists()
    (out/'transport_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    return audit


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();print(json.dumps(convert(a.source,a.output)))
