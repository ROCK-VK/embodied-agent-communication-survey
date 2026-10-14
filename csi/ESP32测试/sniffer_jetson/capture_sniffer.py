"""Read-only serial capture after configuring/resetting the experimental ESP only."""
import argparse, collections, hashlib, json, time
from pathlib import Path
import serial
ap=argparse.ArgumentParser()
ap.add_argument('--port',default='COM10')
ap.add_argument('--baud',type=int,default=921600)
ap.add_argument('--channel',type=int,required=True)
ap.add_argument('--mac',required=True)
ap.add_argument('--seconds',type=int,default=300)
ap.add_argument('--out',required=True)
a=ap.parse_args()
assert len(a.mac.split(':'))==6 and all(len(x)==2 and 0<=int(x,16)<=255 for x in a.mac.split(':'))
r=Path(a.out);r.mkdir(parents=True,exist_ok=True)
s=serial.Serial(port=None,baudrate=a.baud,timeout=.5);s.dtr=False;s.rts=False;s.port=a.port;s.open()
s.rts=True;time.sleep(.1);s.rts=False
wall_start=time.time();initial=time.monotonic();armed=None;stop=None;final=None;last=None
counts=collections.Counter();frames=[];background_frames=[];csis=[];background=[];stats=[];boot=[];armed_data=None;cfg_sent=False
try:
    with (r/'serial_raw.log').open('w',encoding='utf-8') as f:
        while True:
            now=time.monotonic()
            if armed is None and now-initial>60: raise RuntimeError('ESP did not reach ARMED within 60 seconds')
            if armed is not None and stop is None and now-armed>=a.seconds:
                s.write(b'STOP\n');s.flush();stop=now
            if stop is not None and now-stop>15: raise RuntimeError('No FINAL counters after STOP')
            line=s.readline().decode('utf-8',errors='replace').rstrip()
            if not line: continue
            f.write(line+'\n')
            counts['serial_lines']+=1
            if not line.startswith('{'):
                if any(t in line for t in ['ELF file SHA256','Project name','App version','ESP-IDF:','ESP_ERROR_CHECK','abort','assert','Backtrace']):
                    boot.append(line);print(line,flush=True)
                    if 'ESP_ERROR_CHECK' in line or 'abort' in line or 'assert' in line: raise RuntimeError('ESP init/runtime failure; stopping without repeated CFG')
                continue
            try: event=json.loads(line)
            except ValueError: counts['json_parse_errors']+=1;continue
            kind=event.get('event');counts[kind]+=1
            if kind=='READY' and not cfg_sent:
                cfg_sent=True
                s.write(f'CFG,{a.channel},{a.mac}\n'.encode('ascii'));s.flush()
                print('ESP READY; runtime target/channel sent over UART.',flush=True)
            elif kind=='ARMED':
                armed=now;last=now;armed_data=event
                assert event['channel']==a.channel and event['target'].lower()==a.mac.lower()
                print(json.dumps(event),flush=True)
            elif kind=='FRAME': (frames if event.get('target') else background_frames).append(event)
            elif kind=='CSI':
                (csis if event.get('target') else background).append(event)
            elif kind in ('STATS','FINAL'):
                stats.append(event)
                if kind=='FINAL': final=event;break
                if armed is not None and now-last>=30:
                    f.flush();print(json.dumps(event),flush=True);last=now
finally:
    s.close()
# Source-confirmed records must agree with both API source MAC and header TA.
confirmed=[x for x in csis if x.get('ta_present') and x['ta'].lower()==a.mac.lower() and x['source'].lower()==a.mac.lower()]
usable=[x for x in confirmed if x['estimate_valid']==1 and x['rx_state']==0 and x['len']>(4 if x['first_word_invalid'] else 0) and x['copied']==x['len'] and len(x.get('data_hex',''))==2*x['len'] and any(bytes.fromhex(x['data_hex'])[4 if x['first_word_invalid'] else 0:])]
data=[x for x in usable if x['frame_type']==2]
uplink=[x for x in data if x['to_ds']==1 and x['from_ds']==0]
# Same-frame metadata comparison only; not business/sample_id association.
def key(x):return (x['timestamp'],x['ta'],x['fc'],x['seq_ctrl'])
fkeys=collections.Counter(key(x) for x in frames if x.get('ta_present'))
unique_same_frame=sum(fkeys[key(x)]==1 for x in uplink)
if final['prom_target']==0 and final['csi_target']==0: category='A'
elif final['csi_target']==0: category='B'
elif final['prom_target_data']>0 and uplink and unique_same_frame>0 and not final['csi_target_hdr_conflict']: category='D'
else: category='C'
summary={'classification':category,'classification_scope':'observation only; a negative result requires independently verified target availability','compatibility_verdict':'source-confirmed positive' if category=='D' else 'not established; audit target availability and use controlled 20MHz comparison','duration_after_armed_s':time.monotonic()-armed,'armed':armed_data,'final_device_counters':final,'host_events':dict(counts),'target_frame_records_exported':len(frames),'target_csi_records_exported':len(csis),'source_header_confirmed_csi':len(confirmed),'source_confirmed_usable_csi':len(usable),'source_confirmed_data_csi':len(data),'source_confirmed_uplink_data_csi':len(uplink),'unique_timestamp_ta_fc_seq_matches':unique_same_frame,'same_frame_join_scope':'identical RX timestamp/TA/FC/seq only, not UDP/sample_id','target_csi_lengths':dict(collections.Counter(x['len'] for x in csis)),'target_csi_formats':dict(collections.Counter(x['format'] for x in csis)),'target_frame_types':dict(collections.Counter(x['frame_type'] for x in frames)),'target_frame_subtypes':dict(collections.Counter(f"{x['frame_type']}/{x['subtype']}" for x in frames)),'target_frame_formats':dict(collections.Counter(x['format'] for x in frames)),'target_csi_rx_states':dict(collections.Counter(x['rx_state'] for x in csis)),'target_csi_estimate_valid':dict(collections.Counter(x['estimate_valid'] for x in csis)),'target_csi_first_word_invalid':dict(collections.Counter(x['first_word_invalid'] for x in csis)),'target_csi_unique_buffers':len({hashlib.sha256(bytes.fromhex(x['data_hex'])).hexdigest() for x in csis}),'background_frame_samples':len(background_frames),'background_frame_transmitters':dict(collections.Counter(x['ta'] for x in background_frames)),'background_frame_types':dict(collections.Counter(x['frame_type'] for x in background_frames)),'background_csi_sampled':len(background),'background_csi_valid':sum(x['estimate_valid']==1 and x['rx_state']==0 for x in background),'background_source_macs':dict(collections.Counter(x['source'] for x in background)),'boot_evidence':boot,'jetson_modified':False,'runtime_target_mac':a.mac,'host_wall_start':wall_start,'needs_20mhz_control':category!='D','needs_ap_plan_b_now':False}
(r/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print('COMPLETE',json.dumps(summary,ensure_ascii=False),flush=True)
