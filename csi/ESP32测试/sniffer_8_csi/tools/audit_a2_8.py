"""Audit saved CSI API parts without decryption or claims of authenticated tails."""
import argparse,collections,csv,json,subprocess
from pathlib import Path
from wire8 import assemble_api_parts


def audit(records,pcap,tshark,out):
    out.mkdir(parents=True,exist_ok=False)
    rows=[r for r in map(json.loads,records.read_text(encoding='utf-8').splitlines()) if r['event']=='CSI_DATA']
    fields=['frame.number','wlan.ccmp.extiv','wlan.tkip.extiv','_ws.malformed']
    cmd=[str(tshark),'-n','-r',str(pcap),'-o','wlan.enable_decryption:FALSE','-T','fields','-E','separator=/t']
    for field in fields:cmd+=['-e',field]
    proc=subprocess.run(cmd,check=True,capture_output=True,text=True,encoding='utf-8')
    decoded=[x+['']*(4-len(x)) for x in csv.reader(proc.stdout.splitlines(),delimiter='\t')]
    if len(decoded)!=len(rows):raise ValueError('PCAP/index count mismatch')
    details=[]
    for r,t in zip(rows,decoded):
        raw=assemble_api_parts(r);h=r['mac_header'];body=raw[r['hdr_len']:]
        extiv=len(body)>=8 and bool(body[3]&0x20);pn=int.from_bytes(bytes([body[0],body[1],*body[4:8]]),'little') if extiv else None
        d={k:r[k] for k in ('record_serial','hdr_len','payload_len','payload_copied','payload_minus_hdr','wire_sig_len','wire_dump_len')}
        d.update(union_len=len(raw),subtype=h['subtype'],fragment=h['fragment'],more_fragments=h['more_fragments'],amsdu=h['amsdu'],
                 ccmp_display=bool(t[1]),tkip_display=bool(t[2]),malformed=bool(t[3]),ccmp_extiv_candidate=extiv,
                 ccmp_pn_candidate=pn,ciphertext_plus_tag_candidate_len=max(0,len(body)-8),
                 ciphertext_candidate_len_assuming_tag8=max(0,len(body)-16),enough_for_tag8_candidate=len(body)>=16,
                 tkip_heuristic_match=len(body)>=2 and body[1]==((body[0]|0x20)&0x7f))
        details.append(d)
    (out/'record_layout_private.json').write_text(json.dumps(details,indent=2),encoding='utf-8')
    odd=[d for d in details if not d['ccmp_display']]
    result=dict(total=len(details),ccmp_display=sum(d['ccmp_display'] for d in details),tkip_display=sum(d['tkip_display'] for d in details),
                extiv_candidates=sum(d['ccmp_extiv_candidate'] for d in details),enough_tag8_candidates=sum(d['enough_for_tag8_candidate'] for d in details),
                unrecognized_count=len(odd),unrecognized_tkip_heuristic=sum(d['tkip_display'] and d['tkip_heuristic_match'] for d in odd),
                unrecognized_fragmented=sum(bool(d['fragment'] or d['more_fragments']) for d in odd),unrecognized_amsdu=sum(d['amsdu'] for d in odd),
                unrecognized_malformed=sum(d['malformed'] for d in odd),unrecognized_subtypes=dict(collections.Counter(str(d['subtype']) for d in odd)),
                union_lengths=dict(collections.Counter(str(d['union_len']) for d in details)),
                gate_a2_passed=False,reason='Length/ExtIV/PN availability is not tag authentication; real decryption pending approval gate')
    (out/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8');return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--records',type=Path,required=True);p.add_argument('--pcap',type=Path,required=True)
    p.add_argument('--tshark',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    print(json.dumps(audit(a.records,a.pcap,a.tshark,a.output)))
