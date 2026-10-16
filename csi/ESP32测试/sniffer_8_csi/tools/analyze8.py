"""Audit CSI-centric stream and candidate PCAP without decrypting site traffic."""
import argparse,collections,csv,json,struct,subprocess
from pathlib import Path
from wire8 import Decoder,assemble_api_parts


def audit(capture,out,tshark):
    out.mkdir(exist_ok=False);d=Decoder();rows=[]
    with (capture/'stream.bin').open('rb') as f:
        while b:=f.read(65536):rows.extend(d.feed(b))
    transport=d.finish();host=json.loads((capture/'summary.json').read_text())
    times={r['record_serial']:r for r in map(json.loads,(capture/'stream.bin.times.jsonl').read_text().splitlines())}
    for r in rows:r.update(times[r['record_serial']])
    with (out/'records_private.jsonl').open('x',encoding='utf-8') as f:
        for r in rows:f.write(json.dumps(r,separators=(',',':'))+'\n')
    data=[r for r in rows if r['event']=='CSI_DATA'];end=host['final']['counters']
    index=[]
    with (out/'candidate_parts.pcap').open('xb') as f:
        f.write(struct.pack('<IHHIIII',0xa1b23c4d,2,4,0,0,8192,127))
        for r in data:
            if r['truncated']:continue
            # Union verified overlapping API ranges; no guessed tail trim or artificial FCS.
            raw=assemble_api_parts(r);ch=r['channel'];freq=2407+ch*5 if ch<=13 else 5000+ch*5
            rt=struct.pack('<BBHIBxHHb',0,0,15,0x2a,0,freq,0x80 if ch<=14 else 0x100,r['rssi'])
            ns=r['host_time_ns'];packet=rt+raw
            f.write(struct.pack('<IIII',ns//10**9,ns%10**9,len(packet),len(packet)));f.write(packet)
            index.append(r)
    fields=['frame.number','wlan.fc.type_subtype','wlan.ta','wlan.ra','wlan.fc.protected','wlan.ccmp.extiv','llc.type','_ws.malformed']
    cmd=[str(tshark),'-n','-r',str(out/'candidate_parts.pcap'),'-o','wlan.enable_decryption:FALSE','-T','fields','-E','separator=/t']
    for field in fields:cmd+=['-e',field]
    proc=subprocess.run(cmd,check=True,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (out/'tshark_private.tsv').write_text(proc.stdout,encoding='utf-8')
    decoded=[dict(zip(fields,v+['']*(len(fields)-len(v)))) for v in csv.reader(proc.stdout.splitlines(),delimiter='\t')]
    protected=[r for r in data if r['mac_header']['protected']]
    ccmp=sum(bool(r.get('wlan.ccmp.extiv')) for r in decoded)
    ready=host['ready'];abi=[]
    for r in data:
        meta=bytes.fromhex(r['rx_ctrl_hex']);s=ready['sig_first_byte'];t=ready['dump_first_byte']
        abi.append((int.from_bytes(meta[s:s+2],'little')&0x3fff)==r['wire_sig_len'] and (int.from_bytes(meta[t:t+2],'little')&0x3fff)==r['wire_dump_len'])
    errors=sum(transport.get(k,0) for k in ('bad_header','crc_error','discarded_bytes','serial_discontinuity','incomplete_bytes','raw_metadata_conflict'))
    checks=dict(ready=ready['version'] in ('sniffer-8-csi-centric','sniffer-8b-csi-centric'),transport_clean=errors==0,
                final_received=bool(host['final']),counts_closed=end['target_csi']==end['csi_enqueued']+end['csi_drop'] and end['csi_enqueued']==end['csi_output']==len(data),
                zero_queue_drop=end['csi_drop']==end['raw_drop']==0,
                zero_empty_truncated=end['csi_empty']==end['csi_truncated']==end['payload_truncated']==end['payload_missing']==0,
                serial_write_ok=end['write_errors']==0,heap_headroom=end['free_heap']>=32768 and end['min_free_heap']>=16384,
                native_records=bool(data) and all(r['native_callback_binding'] for r in data),
                header_valid=bool(data) and all(r['mac_header']['ta']==r['source'] and r['mac_header']['ta']==r['ta'] and r['mac_header']['ra']==r['ra'] for r in data),
                abi_sig_dump_agree=bool(abi) and all(abi),
                ccmp_observed=ccmp>0)
    # Passing A1 never authenticates a tag; A2 needs independent complete-tail evidence.
    result=dict(gate_a1_passed=all(checks.values()),gate_a2_passed=False,
                gate_a2_status='not_proven_no_independent_authentication_tag_boundary_evidence',checks=checks,
                atomic_records=len(data),protected_records=len(protected),ccmp_standard_records=ccmp,
                abi_ready=ready,final_counters=end,transport=transport,
                hdr_lengths=dict(collections.Counter(str(r['hdr_len']) for r in data)),
                payload_lengths=dict(collections.Counter(str(r['payload_len']) for r in data)),
                csi_lengths=dict(collections.Counter(str(r['csi_len']) for r in data)),
                payload_pointer_deltas=dict(collections.Counter(str(r['payload_minus_hdr']) for r in data)),
                verified_overlap_records=sum(assemble_api_parts(r) is not None for r in data if not r['truncated']),
                union_length_minus_sig=dict(collections.Counter(str(len(assemble_api_parts(r))-r['wire_sig_len']) for r in data if not r['truncated'])),
                phy_formats=dict(collections.Counter(str(r['format']) for r in data)),
                estimate_valid=dict(collections.Counter(str(r['estimate_valid']) for r in data)),
                first_word_invalid=dict(collections.Counter(str(r['first_word_invalid']) for r in data)),
                rx_states=dict(collections.Counter(str(r['rx_state']) for r in data)),
                payload_prefix_classes=dict(collections.Counter('LLC_SNAP' if r['payload_hex'].startswith('aaaa03') else 'other' for r in data)),
                frame_parts_minus_sig=dict(collections.Counter(str(r['hdr_len']+r['payload_len']-r['wire_sig_len']) for r in data)),
                limits=['Native callback association is exported, not a cross-callback MPDU join proof',
                        'Candidate PCAP uses exact API parts; security-field/tail semantics remain to validate',
                        'No tag authentication, decryption, reassociation or active UDP'])
    (out/'analysis.json').write_text(json.dumps(result,indent=2),encoding='utf-8');return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--capture',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--tshark',type=Path,required=True)
    a=p.parse_args();r=audit(a.capture,a.output,a.tshark);print(json.dumps({k:r[k] for k in ('gate_a1_passed','atomic_records','protected_records','ccmp_standard_records','checks')}))
