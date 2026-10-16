"""Capture pair-scoped CSI-centric UART after explicit experiment authorization.

This tool resets the ESP through CH343 RTS when explicitly run. It never changes Jetson networking.
"""
import argparse
import json
import re
import time
from pathlib import Path
import serial
from wire8 import Decoder


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',default='COM10');p.add_argument('--channel',type=int,required=True)
    p.add_argument('--target',required=True);p.add_argument('--ap',required=True)
    p.add_argument('--duration',type=float,default=60);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--stop-file',type=Path,help='Local stop request; never a network control')
    a=p.parse_args()
    if not all(re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}',m) for m in (a.target,a.ap)) or not 1<=a.channel<=196 or a.duration<=0:p.error('invalid pair/channel/duration')
    a.output.mkdir(parents=True,exist_ok=False);d=Decoder();armed=False;final=None
    s=serial.Serial(port=None,baudrate=921600,timeout=.1);s.dtr=False;s.rts=False;s.port=a.port
    with s,(a.output/'stream.bin').open('xb') as raw,(a.output/'stream.bin.times.jsonl').open('x',encoding='utf-8') as times,(a.output/'boot_private.log').open('xb') as boot:
        s.rts=True;time.sleep(.1);s.rts=False;deadline=time.monotonic()+30;ready=None
        while time.monotonic()<deadline:
            line=s.readline();boot.write(line)
            try:r=json.loads(line)
            except (ValueError,UnicodeError):continue
            if r.get('event')=='READY':ready=r;break
        if not ready or ready.get('version')!='sniffer-8b-csi-centric':raise RuntimeError('CSI8 READY not found; no CFG sent')
        s.write(f'CFG,{a.channel},{a.target},{a.ap}\n'.encode());deadline=time.monotonic()+30;stop_sent=False;stop_reason=None
        try:
            while True:
                if armed and not stop_sent and a.stop_file and a.stop_file.exists():
                    stop_reason='local_stop_file';s.write(b'STOP\n');stop_sent=True;deadline=time.monotonic()+30
                if time.monotonic()>=deadline:
                    if armed and not stop_sent:
                        s.write(b'STOP\n');stop_sent=True;deadline=time.monotonic()+30
                    else:break
                chunk=s.read(max(1,min(8192,s.in_waiting)));raw.write(chunk)
                for r in d.feed(chunk):
                    times.write(json.dumps(dict(record_serial=r['record_serial'],host_time_ns=time.time_ns(),host_mono_ns=time.monotonic_ns()))+'\n')
                    if r['event']=='ARMED':
                        c=r['counters']
                        if armed or c['channel']!=a.channel or c['target'].lower()!=a.target.lower() or c['ap'].lower()!=a.ap.lower():raise RuntimeError('ARMED mismatch')
                        armed=True;deadline=time.monotonic()+a.duration
                        print('ARMED CSI8; no network reassociation is performed by this tool',flush=True)
                    if r['event']=='FINAL':final=r;break
                    if r['event']=='STATS' and not stop_sent:
                        c=r['counters']
                        bad=any(c.get(k,0) for k in ('raw_drop','csi_drop','raw_truncated','csi_truncated','payload_truncated','payload_missing','csi_empty','write_errors','hdr_conflict'))
                        if bad or c.get('min_free_heap',0)<16384:
                            stop_reason='resource_gate';s.write(b'STOP\n');stop_sent=True;deadline=time.monotonic()+30
                            print('Resource gate: STOP requested; do not send UDP',flush=True)
                raw.flush();times.flush()
                if final:break
        finally:
            if not final:s.write(b'STOP\n') # Best-effort stop on exceptions; lack of FINAL stays a failure.
    result=dict(ready=ready,armed=armed,final=final,transport=d.finish(),stop_reason=stop_reason,gate_a_requires_separate_audit=True)
    (a.output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if not final:raise RuntimeError('missing FINAL; do not continue UDP/decryption')


if __name__=='__main__':main()
