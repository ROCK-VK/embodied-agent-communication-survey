import csv, json, re, statistics
from pathlib import Path
import argparse
from collections import Counter
ap=argparse.ArgumentParser()
ap.add_argument('directory')
a=ap.parse_args()
r=Path(a.directory)
rows=[]
errors=0
boot=[]
for line in (r/'serial_raw.log').read_text(encoding='utf-8').splitlines():
    if 'CSI_DATA,' in line:
        try:
            v=next(csv.reader([line[line.index('CSI_DATA,'):]]))
            data=json.loads(v[14])
            rows.append({'seq':int(v[1]),'mac':v[2],'rssi':int(v[3]),'channel':int(v[8]),'timestamp':int(v[9]),'rx_format':int(v[11]),'len':int(v[12]),'first_word':int(v[13]),'array_len':len(data),'nonzero':any(x!=0 for x in data)})
        except (ValueError,IndexError,StopIteration): errors+=1
    elif any(k in line for k in ['connected with','got ip:','ELF file SHA256','ESP-IDF:','BSS bandwidth','phytype(0x']):
        boot.append(line[line.find('I ('):] if 'I (' in line else line)
wraps=0
last=None
for row in rows:
    t=row['timestamp']
    if last is not None and t<last: wraps+=1
    row['unwrapped_us']=t+wraps*(1<<32)
    last=t
span=(rows[-1]['unwrapped_us']-rows[0]['unwrapped_us'])/1e6 if len(rows)>1 else None
res={'csi_records':len(rows),'parse_errors':errors,'lengths':dict(Counter(x['len'] for x in rows)),'length_mismatches':sum(x['len']!=x['array_len'] for x in rows),'source_macs':dict(Counter(x['mac'] for x in rows)),'channels':dict(Counter(x['channel'] for x in rows)),'rx_formats':dict(Counter(x['rx_format'] for x in rows)),'first_word_invalid':dict(Counter(x['first_word'] for x in rows)),'all_zero_records':sum(not x['nonzero'] for x in rows),'rssi_min':min((x['rssi'] for x in rows),default=None),'rssi_max':max((x['rssi'] for x in rows),default=None),'rssi_median':statistics.median(x['rssi'] for x in rows) if rows else None,'csi_time_span_s':span,'observed_records_per_s':(len(rows)-1)/span if span else None,'seq_discontinuities':sum(b['seq']!=a['seq']+1 for a,b in zip(rows,rows[1:])),'boot_evidence':boot,'channel_estimate_validity':'unknown: upstream does not export valid flag; nonzero is not proof of physical validity'}
(r/'analysis_summary.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in res.items() if k!='boot_evidence'},ensure_ascii=False))
