"""Gate A audit of saved raw7 capture; tshark structure only, decryption DISABLED."""
import argparse
import collections
import csv
import json
import subprocess
from pathlib import Path
from raw7 import join,UPLINK,EAPOL


def ccmp_layout(row):
    raw=bytes.fromhex(row['raw_hex']);h=row['mac_header'];n=h['header_len']
    if not h['protected'] or len(raw)<n+16:return None
    iv=raw[n:n+8]
    if iv[2]!=0 or not iv[3]&0x20 or iv[3]&0x1f:return None
    pn=int.from_bytes(iv[:2]+iv[4:8],'little')
    return dict(mac_header_len=n,ccmp_header_len=8,pn=pn,key_id=iv[3]>>6,
                encrypted_payload_len=len(raw)-n-16,tag_len_by_ccmp128_format=8,
                tag_cryptographically_verified=False,
                tag_present_at_exported_tail_is_candidate_only=True)


def audit(capture,converted,tshark,target,ap):
    host=json.loads((capture/'summary.json').read_text(encoding='utf-8'))
    transport=json.loads((converted/'transport_audit.json').read_text(encoding='utf-8'))
    rows=[json.loads(l) for l in (converted/'records.jsonl').read_text(encoding='utf-8').splitlines()]
    frames=[r for r in rows if r['event']=='FRAME'];csi=[r for r in rows if r['event']=='CSI']
    up=[r for r in frames if r['flags']&UPLINK]
    protected=[r for r in up if r['mac_header']['protected']]
    final=host['final']['counters'];pairs=join(rows)
    fields=['frame.number','wlan.fc.type_subtype','wlan.ta','wlan.ra','wlan.fc.protected',
            'wlan.seq','wlan.frag','wlan.ccmp.extiv','_ws.malformed']
    cmd=[str(tshark),'-n','-r',str(converted/'frames.pcap'),'-o','wlan.enable_decryption:FALSE',
         '-T','fields','-E','separator=/t']
    for f in fields:cmd+=['-e',f]
    p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',check=True)
    # Local only: endpoint-bearing standard-tool output is never published.
    (capture/'tshark_structure_private.tsv').write_text(p.stdout,encoding='utf-8')
    (capture/'tshark_structure_stderr.txt').write_text(p.stderr,encoding='utf-8')
    decoded=[]
    for values in csv.reader(p.stdout.splitlines(),delimiter='\t'):
        decoded.append(dict(zip(fields,values+['']*(len(fields)-len(values)))))
    index=json.loads((converted/'frame_index.json').read_text(encoding='utf-8'))
    by_serial={r['record_serial']:r for r in frames}
    dby_num={int(d['frame.number']):d for d in decoded}
    verified=[];conflicts=[]
    for i in index:
        r=by_serial[i['record_serial']];d=dby_num[i['pcap_frame_number']]
        if r not in protected:continue
        layout=ccmp_layout(r)
        ta=d.get('wlan.ta','').lower();ra=d.get('wlan.ra','').lower()
        pn=d.get('wlan.ccmp.extiv','')
        try:standard_pn=int(pn,0)
        except ValueError:standard_pn=None
        ok=bool(layout and ta==target.lower() and ra==ap.lower() and d['wlan.fc.protected'].lower() in ('1','true')
                and standard_pn==layout['pn'] and not d.get('_ws.malformed'))
        (verified if ok else conflicts).append(r['record_serial'])
    counts=collections.Counter(r['event'] for r in rows)
    expected_wire=sum(66+r['copied'] for r in rows if r['event']!='FINAL')
    checks=dict(
        ready=host['ready']['version'] in ('sniffer-7a-raw-uplink','sniffer-7b-raw-snapshot'),
        armed_final=host['armed'] and host['final']['event']=='FINAL',
        raw_scope=all((r['flags']&UPLINK and r['ta'].lower()==target.lower() and r['ra'].lower()==ap.lower()) or (r['flags']&EAPOL and r['ta'].lower()==ap.lower() and r['ra'].lower()==target.lower()) for r in frames),
        raw_queue_closed=final['pair_frames']==final['raw_enqueued']+final['raw_drop']+final.get('raw_scope_changed',0) and final['raw_enqueued']==final['raw_output']==len(frames),
        csi_queue_closed=final['target_csi']==final['csi_enqueued']+final['csi_drop'] and final['csi_enqueued']==final['csi_output']==len(csi),
        zero_drop=final['raw_drop']==final['csi_drop']==final.get('raw_scope_changed',0)==0,
        zero_serial_errors=final['write_errors']==0,
        binary_clean=not any(transport.get(k,0) for k in ('discarded_bytes','bad_header','crc_error','serial_discontinuity','incomplete_bytes','raw_metadata_conflict')),
        no_empty_truncated=final['csi_empty']==final['csi_truncated']==final['raw_truncated']==0,
        length_complete=all(r['copied']==r['original_len'] and not r['truncated'] for r in frames+csi),
        raw_length_contract_consistent=all(r['original_len']<=r['sig_len'] for r in frames),
        wire_bytes_closed=expected_wire==final['wire_bytes_before_control'],
        csi_valid_source=bool(csi) and all(r['source'].lower()==r['ta'].lower()==target.lower() and r['ra'].lower()==ap.lower() and r['estimate_valid']==1 and r['rx_state']==0 for r in csi),
        pcap_complete=len(index)==len(frames)==len(decoded),
        ccmp_structure=bool(protected) and len(verified)==len(protected) and not conflicts,
        metadata_matching=any(r['unique'] for r in pairs))
    return dict(gate_a_passed=all(checks.values()),checks=checks,duration_s=(host['final']['esp_mono_us']-next(r['esp_mono_us'] for r in rows if r['event']=='ARMED'))/1e6,
                firmware=host['ready']['version'],event_counts=dict(counts),final_counters=final,transport=transport,
                uplink_frames=len(up),protected_uplink_frames=len(protected),ccmp_structure_verified=len(verified),ccmp_structure_conflicts=len(conflicts),
                frame_formats=dict(collections.Counter(str(r['format']) for r in frames)),csi_formats=dict(collections.Counter(str(r['format']) for r in csi)),
                csi_lengths=dict(collections.Counter(str(r['original_len']) for r in csi)),
                shared_metadata_keys=len(pairs),unique_metadata_keys=sum(r['unique'] for r in pairs),ambiguous_metadata_keys=sum(not r['unique'] for r in pairs),
                raw_sig_minus_dump=dict(collections.Counter(str(r['sig_len']-r['copied']) for r in frames)),
                mic_scope='8-byte exported tail is only a CCMP128 tag candidate; raw dump/sig length semantics must be reconciled first. No MIC authentication/decryption attempted.',
                raw_examples=[dict(record_serial=r['record_serial'],raw_len=r['original_len'],header_len=r['mac_header']['header_len'],address4_present=r['mac_header']['address4'] is not None,qos_present=r['mac_header']['qos_control'] is not None,**(ccmp_layout(r) or {})) for r in protected[:5]],
                limits=['Not a wireless capture rate','No reassociation/active UDP/decryption; EAPOL only if naturally present','FCS excluded by SDK; no FCS fabricated','CCMP structural verification does not authenticate MIC or prove future decryption'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('capture','converted','tshark','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--target',required=True);p.add_argument('--ap',required=True)
    a=p.parse_args();r=audit(a.capture,a.converted,a.tshark,a.target,a.ap)
    with a.output.open('x',encoding='utf-8') as f:json.dump(r,f,indent=2)
    print(json.dumps({k:r[k] for k in ('gate_a_passed','checks','uplink_frames','protected_uplink_frames','ccmp_structure_verified','unique_metadata_keys')}))
