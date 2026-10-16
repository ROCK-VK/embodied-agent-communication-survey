"""Check saved synthetic payload/CSI byte patterns, EAPOL lengths and provenance."""
import argparse,json
from pathlib import Path
from wpa2_gate8c import read_stream,parse_eapol

def audit(capture):
 rows,health=read_stream(capture);data=[r for r in rows if r['event']=='CSI_DATA'];eapol=[r for r in rows if r['event']=='FRAME']
 payload=b'\0\0'+bytes((j*7+11)&255 for j in range(26,152));csi=bytes((j*3+5)&255 for j in range(114))
 checks=dict(payload_pattern=all(bytes.fromhex(r['payload_hex'])==payload for r in data),
             csi_pattern=all(bytes.fromhex(r['csi_hex'])==csi for r in data),
             synthetic_provenance=all(r['flags']&16 for r in data+eapol),
             no_real_rf=all(not r['counters'].get('rf_capture_enabled',False) for r in rows if 'counters' in r))
 parsed=[parse_eapol(bytes.fromhex(r['raw_hex']),'02:00:00:00:00:01','02:00:00:00:00:02') for r in eapol]
 checks['eapol_complete']=all(p['eapol_length']==99 and p['message'] in (1,2,3,4) for p in parsed)
 return dict(passed=all(checks.values()),checks=checks,atomic_records=len(data),eapol_records=len(eapol),transport=health,scope='Synthetic only; EAPOL MIC bytes are dummy and not cryptographically valid')

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);a=p.parse_args()
 result={name:audit(a.base/name) for name in ['synthetic_probe100','synthetic_probe200','synthetic_handshake','synthetic_mode_cycle']}
 (a.base/'synthetic_post_audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps({k:v['passed'] for k,v in result.items()}))
 if not all(v['passed'] for v in result.values()):raise SystemExit(2)
