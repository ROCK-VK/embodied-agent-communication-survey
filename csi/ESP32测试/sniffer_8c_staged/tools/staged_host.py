"""8c mode/session transport and explicitly synthetic workload runner.

This CLI always uses CFG,SYNTH and never configures a real Wi-Fi target.
"""
import argparse,json,sys,time,collections
from pathlib import Path
import serial
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'uart_benchmark/tools'))
from benchmark_host import connect
from wire8c import Decoder,assemble_api_parts

MODES={'HANDSHAKE':'HANDSHAKE_ONLY','PROBE':'PROBE_CAPTURE','STOP':'STOP'}
def validate_ack(r,mode):
 c=r.get('counters',{})
 if r.get('event')!='CONTROL' or c.get('event')!='MODE_ACK' or c.get('mode')!=MODES[mode] or c.get('counters_reset') is not False:
  raise ValueError('Mode was not acknowledged')
 return c

class Session:
 def __init__(self,s,out):
  self.s=s;self.out=out;self.d=Decoder();self.rows=[];self.pending=[]
  self.raw=(out/'stream.bin').open('xb');self.times=(out/'stream.bin.times.jsonl').open('x',encoding='utf-8')
 def send(self,line):self.s.write((line+'\n').encode())
 def wait(self,event,timeout=15):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   while self.pending:
    r=self.pending.pop(0)
    if r['event']==event or r.get('counters',{}).get('event')==event:return r
   b=self.s.read(max(1,min(65536,self.s.in_waiting)));self.raw.write(b)
   for r in self.d.feed(b):
    t=dict(record_serial=r['record_serial'],host_time_ns=time.time_ns(),host_mono_ns=time.monotonic_ns());r.update(t)
    self.times.write(json.dumps(t)+'\n');self.rows.append(r);self.pending.append(r)
    c=r.get('counters',{})
    if c.get('event') in ('ERROR','BUSY'):raise RuntimeError('Firmware rejected command: '+c['event'])
    if c and any(c.get(k,0) for k in ('queue_drop','write_errors','raw_truncated','csi_truncated','payload_truncated','payload_missing','csi_empty','hdr_conflict')):
     self.send('MODE STOP');raise RuntimeError('Resource gate stopped synthetic test')
   self.raw.flush();self.times.flush()
  raise RuntimeError('Missing acknowledged event '+event)
 def mode(self,mode):
  self.send('MODE '+mode);return validate_ack(self.wait('MODE_ACK'),mode)
 def close(self):self.raw.close();self.times.close()

def main():
 p=argparse.ArgumentParser();p.add_argument('--port',default='COM10');p.add_argument('--baud',type=int,default=3000000);p.add_argument('--mode',choices=['HANDSHAKE','PROBE','CYCLE'],required=True);p.add_argument('--rate',type=int,default=100);p.add_argument('--seconds',type=int,default=30);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 a.output.mkdir(parents=True,exist_ok=False);s=serial.Serial(port=None,baudrate=921600,timeout=.1);s.dtr=False;s.rts=False;s.port=a.port;session=None;results=[]
 with s:
  ready,br=connect(s,'sniffer-8c-staged-capture',a.baud);session=Session(s,a.output)
  try:
   session.send('CFG,SYNTH');cfg=session.wait('CONFIGURED')['counters'];assert cfg['synthetic'] and not cfg['rf_capture_enabled']
   phases=['HANDSHAKE','PROBE'] if a.mode=='CYCLE' else [a.mode]
   for phase in phases:
    ack=session.mode(phase);assert ack['queue_pending']==0 and not ack['rf_capture_enabled'];begin=len(session.rows)
    session.send(f'SYNTH {a.rate} {a.seconds}');session.wait('SYNTH_ACK');print('Synthetic workload ARMED: '+phase,flush=True)
    done=session.wait('SYNTH_DONE',a.seconds+15)['counters'];subset=session.rows[begin:];data=[r for r in subset if r['event']=='CSI_DATA'];raw=[r for r in subset if r['event']=='FRAME'];n=a.rate*a.seconds
    check=dict(candidate_count=len(data)==(n if phase=='PROBE' else 0),eapol_count=len(raw)==a.seconds,
               candidate_callback=done['candidate_seen']-ack['candidate_seen']==(n if phase=='PROBE' else 0),
               filtered_large=done['large_frame_filtered']-ack['large_frame_filtered']==(4*n if phase=='PROBE' else 0),
               counted_handshake_data=done['handshake_data_count']-ack['handshake_data_count']==(5*n if phase=='HANDSHAKE' else 0),
               enqueue_output=done['candidate_enqueued']==done['candidate_output'] and done['raw_enqueued']==done['raw_output'],
               synthetic_flags=all(r['flags']&16 for r in data+raw),heap=done['min_free_heap']>=16384,
               complete_segments=all(r['payload_copied']==r['payload_len'] and r['csi_copied']==r['csi_len']==114 and not r['truncated'] for r in data),
               union=all(len(assemble_api_parts(r))==152 for r in data),
               csi_bytes=all(bytes.fromhex(r['csi_hex'])==bytes((i*3+5)&255 for i in range(114)) for r in data))
    results.append(dict(phase=phase,expected_candidates=n,expected_large=4*n,checks=check,ack=ack,done=done,host_candidates=len(data),host_eapol=len(raw)))
   session.mode('STOP');final=session.wait('FINAL');health=session.d.finish()
  finally:
   if session:session.close()
 bad=any(health.get(k,0) for k in ('bad_header','crc_error','discarded_bytes','serial_discontinuity','incomplete_bytes','raw_metadata_conflict'))
 result=dict(passed=all(all(r['checks'].values()) for r in results) and not bad,scope='Synthetic callback throughput only; no real RF capture enabled',ready=ready,baud=br,phases=results,transport=health,final=final['counters'])
 (a.output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result));return 0 if result['passed'] else 2
if __name__=='__main__':raise SystemExit(main())
