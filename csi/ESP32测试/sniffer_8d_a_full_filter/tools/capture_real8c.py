"""Pair-scoped real 8c capture. Controls ESP UART only, never Jetson networking.

External commands file accepts PROBE (only after coherent four-way) or STOP.
All packet bytes/nonces remain in private local files. No Wi-Fi password option.
"""
import argparse,json,re,sys,time
from pathlib import Path
import serial
from staged_host import validate_ack
from benchmark_host import connect
from wire8c import Decoder
from wpa2_gate8c import parse_eapol,handshake

ERRORS=('queue_drop','raw_drop','csi_drop','raw_truncated','csi_truncated','payload_truncated','payload_missing','csi_empty','hdr_conflict','write_errors')
TRANSPORT_ERRORS=('bad_header','crc_error','discarded_bytes','serial_discontinuity','raw_metadata_conflict')
def probe_allowed(exchange,counters):
 return bool(exchange['complete_four_way'] and counters and not any(counters.get(k,0) for k in ERRORS) and counters.get('min_free_heap',0)>=16384)

def main():
 p=argparse.ArgumentParser();p.add_argument('--port',default='COM10');p.add_argument('--channel',type=int,required=True);p.add_argument('--target',required=True);p.add_argument('--ap',required=True)
 p.add_argument('--baud',type=int,default=3000000);p.add_argument('--duration',type=float,default=240);p.add_argument('--commands',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 p.add_argument('--expected-version',default='sniffer-8d-a-full-filter');a=p.parse_args()
 for m in (a.target,a.ap):
  if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}',m):p.error('MAC format')
 if not 1<=a.channel<=196 or not 0<a.duration<=600:p.error('channel/duration')
 a.target=a.target.lower();a.ap=a.ap.lower();a.output.mkdir(parents=True,exist_ok=False)
 d=Decoder();eapol=[];rejected=[];ready=br=final=None;counters={};mode='STOP';pending=None;configured=False;handshake_announced=False
 stop_reason=None;stop_sent=False;stop_deadline=None;command_count=0;acks=[];frames=0;started=time.monotonic();last_state=0
 s=serial.Serial(port=None,baudrate=921600,timeout=.1);s.dtr=False;s.rts=False;s.port=a.port
 def send(command):s.write((command+'\n').encode())
 def request_stop(reason):
  nonlocal stop_reason,stop_sent,stop_deadline,pending
  if not stop_sent:
   stop_reason=reason;stop_sent=True;stop_deadline=time.monotonic()+20;pending='STOP';send('MODE STOP')
 def state():
  return dict(mode=mode,mode_ack_pending=pending,handshake=handshake(eapol),rejected_eapol=len(rejected),
              atomic_records=frames,counters=counters,transport=dict(d.counts),stop_reason=stop_reason,final_received=bool(final))
 def save_state():
  # Atomic replace prevents a control client from reading partially written JSON.
  tmp=a.output/'state.tmp';tmp.write_text(json.dumps(state(),indent=2),encoding='utf-8');tmp.replace(a.output/'state.json')
 with s,(a.output/'stream.bin').open('xb') as raw,(a.output/'stream.bin.times.jsonl').open('x',encoding='utf-8') as times:
  try:
   ready,br=connect(s,a.expected_version,a.baud)
   (a.output/'ready.json').write_text(json.dumps(dict(ready=ready,baud=br),indent=2),encoding='utf-8')
   send(f'CFG,{a.channel},{a.target},{a.ap}');setup_deadline=time.monotonic()+20
   while not final:
    now=time.monotonic()
    if not configured and now>setup_deadline:raise RuntimeError('missing real CONFIGURED')
    if now-started>a.duration:request_stop('duration_limit')
    if stop_deadline and now>stop_deadline:break
    b=s.read(max(1,min(65536,s.in_waiting)));raw.write(b)
    for r in d.feed(b):
     times.write(json.dumps(dict(record_serial=r['record_serial'],host_time_ns=time.time_ns(),host_mono_ns=time.monotonic_ns()))+'\n')
     if r['flags']&16:request_stop('unexpected_synthetic_record')
     if r['event']=='FRAME':
      try:q=parse_eapol(bytes.fromhex(r['raw_hex']),a.target,a.ap);q['record_serial']=r['record_serial'];eapol.append(q)
      except ValueError as exc:rejected.append(dict(record_serial=r['record_serial'],reason=str(exc)))
     if r['event']=='CSI_DATA':frames+=1
     c=r.get('counters')
     if c:
      counters=c
      if c.get('synthetic'):request_stop('unexpected_synthetic_mode')
      if c.get('event')=='CONFIGURED':
       if configured:raise RuntimeError('duplicate CONFIGURED')
       configured=True;pending='HANDSHAKE';send('MODE HANDSHAKE')
      elif c.get('event')=='MODE_ACK':
       if not pending:raise RuntimeError('unsolicited MODE_ACK')
       validate_ack(r,pending)
       if c['rf_capture_enabled']!=(pending!='STOP'):raise RuntimeError('RF state mismatch')
       mode=c['mode'];acks.append(c);pending=None;print('MODE_ACK '+mode,flush=True)
      elif c.get('event') in ('ERROR','BUSY'):request_stop('firmware_'+c['event'])
      if any(c.get(k,0) for k in ERRORS) or c.get('min_free_heap',0)<16384:request_stop('resource_gate')
     if r['event']=='FINAL':final=r;break
    raw.flush();times.flush()
    if any(d.counts.get(k,0) for k in TRANSPORT_ERRORS):request_stop('transport_gate')
    if handshake(eapol)['complete_four_way'] and not handshake_announced:
     print('Coherent M1/M2/M3/M4 structure observed; no crypto validation claimed',flush=True);handshake_announced=True
    if a.commands.exists() and not stop_sent:
     text=a.commands.read_text(encoding='utf-8');lines=text.splitlines()
     if text and not text.endswith('\n'):lines=lines[:-1]
     for command in lines[command_count:]:
      command_count+=1
      if command=='STOP':request_stop('local_stop_command');break
      elif command=='PROBE':
       if pending or mode!='HANDSHAKE_ONLY' or not probe_allowed(handshake(eapol),counters):request_stop('probe_gate_rejected');break
       pending='PROBE';send('MODE PROBE')
      else:request_stop('invalid_local_command');break
    if now-last_state>=.5:save_state();last_state=now
  finally:
   if configured and not final:
    send('MODE STOP') # Best effort; missing FINAL remains explicitly failed.
   save_state()
 result=dict(ready=ready,baud=br,final=final,acks=acks,handshake=handshake(eapol),eapol_records=eapol,rejected_eapol=rejected,
             transport=d.finish(),stop_reason=stop_reason,atomic_records=frames,serial_closed=True)
 (a.output/'summary_private.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 print(json.dumps(dict(final_received=bool(final),handshake=result['handshake'],atomic_records=frames,stop_reason=stop_reason)))
 return 0 if final and stop_reason=='local_stop_command' else 2
if __name__=='__main__':raise SystemExit(main())
