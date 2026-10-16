"""Future authorized experiment only: capture pair-scoped raw7 UART; never flashes/reconnects.

This tool resets the ESP through CH343 RTS when explicitly run. Not executed in preparation.
"""
import argparse
import json
import re
import time
from pathlib import Path
import serial
from raw7 import Decoder


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',default='COM10');p.add_argument('--channel',type=int,required=True)
    p.add_argument('--target',required=True);p.add_argument('--ap',required=True)
    p.add_argument('--duration',type=float,default=60);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if not all(re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}',m) for m in (a.target,a.ap)) or not 1<=a.channel<=196 or a.duration<=0:p.error('invalid pair/channel/duration')
    a.output.mkdir(parents=True,exist_ok=False);d=Decoder();armed=False;final=None
    s=serial.Serial(port=None,baudrate=921600,timeout=.1);s.dtr=False;s.rts=False;s.port=a.port
    with s,(a.output/'stream.bin').open('xb') as raw,(a.output/'stream.bin.times.jsonl').open('x',encoding='utf-8') as times:
        s.rts=True;time.sleep(.1);s.rts=False;deadline=time.monotonic()+30;ready=None
        while time.monotonic()<deadline:
            line=s.readline()
            try:r=json.loads(line)
            except (ValueError,UnicodeError):continue
            if r.get('event')=='READY':ready=r;break
        if not ready or ready.get('version')!='sniffer-7-raw-binary':raise RuntimeError('raw7 READY not found; no CFG sent')
        s.write(f'CFG,{a.channel},{a.target},{a.ap}\n'.encode());deadline=time.monotonic()+30;stop_sent=False
        try:
            while True:
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
                        print('ARMED raw7; no network reassociation is performed by this tool',flush=True)
                    if r['event']=='FINAL':final=r;break
                if final:break
        finally:
            if not final:s.write(b'STOP\n') # Best-effort stop on exceptions; lack of FINAL stays a failure.
    result=dict(ready=ready,armed=armed,final=final,transport=d.finish(),hardware_capture_validated=False)
    (a.output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if not final:raise RuntimeError('missing FINAL; do not continue UDP/decryption')


if __name__=='__main__':main()
