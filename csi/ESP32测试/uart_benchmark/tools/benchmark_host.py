"""Strict deterministic binary UART benchmark; no Wi-Fi access or payload capture."""
import argparse,collections,json,struct,time,zlib
from pathlib import Path
import serial
H=struct.Struct('<4sBBHII')

class Parser:
 def __init__(self):self.buf=bytearray();self.c=collections.Counter();self.expected=1;self.seen=set();self.final=None
 def feed(self,b):
  self.buf+=b
  while len(self.buf)>=16:
   if self.buf[:4]!=b'UB8C':self.c['resync']+=1;del self.buf[0];continue
   magic,v,k,hl,seq,n=H.unpack_from(self.buf)
   if v!=1 or k not in (1,2) or hl!=16 or n>4096:self.c['malformed']+=1;del self.buf[0];continue
   if len(self.buf)<20+n:break
   block=bytes(self.buf[:20+n]);del self.buf[:20+n]
   if zlib.crc32(block[:-4])!=int.from_bytes(block[-4:],'little'):self.c['crc_error']+=1;continue
   if seq!=self.expected:self.c['serial_gap']+=1
   self.expected=seq+1
   if seq in self.seen:self.c['duplicate']+=1
   self.seen.add(seq);self.c['total_bytes']+=len(block)
   if k==1:
    self.c['received']+=1
    if block[16:-4]!=bytes((i*17+23)&255 for i in range(n)):self.c['pattern_error']+=1
   else:self.final=json.loads(block[16:-4])

def readline(s,event,deadline=10):
 end=time.monotonic()+deadline
 while time.monotonic()<end:
  line=s.readline();begin=line.find(b'{')
  try:r=json.loads(line[begin:] if begin>=0 else b'')
  except (ValueError,UnicodeError):continue
  if r.get('event')==event:return r
 raise RuntimeError('missing '+event)

def connect(s,version,baud):
 s.rts=True;time.sleep(.1);s.rts=False;ready=readline(s,'READY',20)
 if ready['version']!=version:raise RuntimeError('unexpected firmware')
 s.write(f'SET_BAUD {baud}\n'.encode());ack=readline(s,'BAUD_ACK')
 if ack['requested']!=baud:raise RuntimeError('baud ACK mismatch')
 s.baudrate=baud;r=readline(s,'BAUD_READY')
 if r['requested']!=baud:raise RuntimeError('BAUD_READY mismatch')
 return ready,r

def main():
 p=argparse.ArgumentParser();p.add_argument('--port',default='COM10');p.add_argument('--baud',type=int,required=True);p.add_argument('--rate',type=int,required=True);p.add_argument('--seconds',type=int,default=30);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 a.output.mkdir(parents=True,exist_ok=False);s=serial.Serial(port=None,baudrate=921600,timeout=.1);s.dtr=False;s.rts=False;s.port=a.port;d=Parser()
 with s:
  ready,br=connect(s,'uart-benchmark-8c',a.baud);s.write(f'START {a.rate} {a.seconds} 1004\n'.encode());ack=readline(s,'START_ACK');print('BAUD_READY verified; UART synthetic benchmark started',flush=True)
  start=time.perf_counter();deadline=start+a.seconds+15
  with (a.output/'synthetic_stream.bin').open('xb') as f:
   while not d.final and time.perf_counter()<deadline:
    b=s.read(max(1,min(65536,s.in_waiting)));f.write(b);d.feed(b)
  elapsed=time.perf_counter()-start
  s.write(b'STOP\n');readline(s,'STOPPED')
 errors=sum(d.c[k] for k in ('serial_gap','duplicate','crc_error','malformed','resync','pattern_error'))
 expected=ack['expected'];loss=expected-d.c['received'];passed=bool(d.final) and not errors and not loss and not d.buf and d.final['write_errors']==0 and d.final['expected']==expected
 result=dict(passed=passed,baud_requested=a.baud,baud_negotiated=br,rate_requested=a.rate,expected=expected,host_loss=loss,elapsed_s=elapsed,measured_data_wire_Bps=d.c['received']*ack['wire_size']/elapsed,counters=dict(d.c),incomplete_bytes=len(d.buf),final=d.final,scope='UART synthetic throughput only; Wi-Fi not initialized')
 (a.output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result));return 0 if passed else 2
if __name__=='__main__':raise SystemExit(main())
