"""Offline/live-snapshot CSI8 PCAP and strict pairwise WPA2 handshake audit.

Never controls an interface or performs cryptography. All frame/nonce/MIC detail
outputs are private evidence and must not be added to the public allowlist.
"""
import argparse, collections, hashlib, json, struct
from pathlib import Path
from wire8c import Decoder, assemble_api_parts, parse_header


def read_stream(capture, live=False):
    d=Decoder();rows=[]
    with (capture/'stream.bin').open('rb') as f:
        while b:=f.read(65536):rows.extend(d.feed(b))
    health=d.finish()
    # A growing file can end mid-record; never hide complete-record corruption.
    errors=('bad_header','crc_error','discarded_bytes','serial_discontinuity','raw_metadata_conflict')
    if any(health.get(k,0) for k in errors) or (not live and health.get('incomplete_bytes',0)):
        raise ValueError('damaged transport: '+str(health))
    text=(capture/'stream.bin.times.jsonl').read_text(encoding='utf-8')
    if live and not text.endswith('\n'):text=text.rsplit('\n',1)[0]+'\n' if '\n' in text else ''
    times={r['record_serial']:r for r in map(json.loads,text.splitlines())}
    for r in rows:
        if r['record_serial'] not in times:
            if live:continue
            raise ValueError('missing host timing')
        r.update(times[r['record_serial']])
    return [r for r in rows if 'host_time_ns' in r],health


def parse_eapol(raw, target, ap):
    h=parse_header(raw);ta=h['ta'];ra=h['ra']
    if (ta,ra) not in ((target,ap),(ap,target)):raise ValueError('foreign pair')
    if h['protected'] or h['fragment'] or h['more_fragments'] or h['amsdu']:
        raise ValueError('not a complete clear unfragmented EAPOL MPDU')
    b=raw[h['header_len']:]
    if len(b)<6 or b[:6]!=bytes.fromhex('aaaa03000000'):raise ValueError('not LLC/SNAP')
    if len(b)<8:raise ValueError('truncated LLC/SNAP EtherType')
    if b[6:8]!=bytes.fromhex('888e'):raise ValueError('not EtherType 0x888e')
    e=b[8:]
    if len(e)<4 or e[1]!=3:raise ValueError('not EAPOL-Key')
    n=int.from_bytes(e[2:4],'big')
    if n<95 or len(e)<4+n:raise ValueError('truncated EAPOL-Key')
    e=e[:4+n];info=int.from_bytes(e[5:7],'big');replay=int.from_bytes(e[9:17],'big')
    nonce=e[17:49];mic=e[81:97];kd=int.from_bytes(e[97:99],'big')
    if len(e)!=99+kd:raise ValueError('EAPOL key-data length mismatch')
    pair=bool(info&8);ack=bool(info&0x80);hasmic=bool(info&0x100);secure=bool(info&0x200);install=bool(info&0x40)
    msg=None
    if pair and not info&(0x400|0x800|0x2000) and (info&7)==2 and e[4]==2:
        if ta==ap and ack and not hasmic and not install and not secure and any(nonce) and not any(mic):msg=1
        elif ta==target and not ack and hasmic and not secure and not install and any(nonce) and any(mic):msg=2
        elif ta==ap and ack and hasmic and install and secure and any(nonce) and any(mic):msg=3
        elif ta==target and not ack and hasmic and secure and not install and not any(nonce) and any(mic):msg=4
    direction='jetson_to_ap' if ta==target and ra==ap else 'ap_to_jetson'
    return dict(message=msg,key_info=info,descriptor=e[4],descriptor_version=info&7,replay_counter=replay,
                nonce=nonce.hex(),mic=mic.hex(),eapol_length=len(e),trailing_bytes=len(b)-8-len(e),
                ta=ta,ra=ra,direction=direction,to_ds=h['to_ds'],from_ds=h['from_ds'],
                subtype=h['subtype'],header_len=h['header_len'],seq_ctrl=h['seq_ctrl'],retry=h['retry'])


def inspect_llc_snap(raw):
    """Return clear Data LLC/SNAP metadata without assuming the EtherType."""
    h=parse_header(raw)
    if h['protected'] or h['fragment'] or h['more_fragments'] or h['amsdu']:
        raise ValueError('not a complete clear unfragmented Data MPDU')
    body=raw[h['header_len']:]
    if len(body)<6 or body[:6]!=bytes.fromhex('aaaa03000000'):
        raise ValueError('not LLC/SNAP')
    if len(body)<8:raise ValueError('truncated LLC/SNAP EtherType')
    return dict(header=h,llc_snap=True,ether_type=int.from_bytes(body[6:8],'big'),body_length=len(body))


def classify_record(r,target,ap):
    """Classify one FRAME or CSI_DATA; CSI validity stays attached to its own record."""
    if r['event']=='CSI_DATA':
        raw=assemble_api_parts(r)
    elif r['event'] in ('RAW','FRAME'):
        if r.get('truncated'):raise ValueError('truncated FRAME record')
        raw=bytes.fromhex(r['raw_hex'])
    else:raise ValueError('unsupported record event')
    result=parse_eapol(raw,target,ap)
    csi_record=r['event']=='CSI_DATA'
    csi_complete=bool(csi_record and r.get('csi_copied')==r.get('csi_len'))
    result.update(source_event=r['event'],record_serial=r['record_serial'],rx_seq=r.get('rx_seq'),
                  same_record_csi=csi_record,csi_present=bool(csi_record and r.get('csi_copied',0)>0),
                  csi_len=r.get('csi_len',0) if csi_record else 0,
                  csi_complete=csi_complete,
                  csi_valid=bool(csi_complete and r.get('csi_len',0)>0 and r.get('estimate_valid')==1 and r.get('rx_state')==0),
                  first_word_invalid=r.get('first_word_invalid') if csi_record else None,
                  estimate_valid=r.get('estimate_valid') if csi_record else None,
                  rx_state=r.get('rx_state') if csi_record else None)
    return result,raw


def handshake(records):
    groups={n:[r for r in records if r['message']==n] for n in range(1,5)};chosen=None
    # Require one coherent ordered exchange, not four messages from different sessions.
    for m1 in groups[1]:
        for m2 in groups[2]:
            if not (m1['record_serial']<m2['record_serial'] and m1['replay_counter']==m2['replay_counter']):continue
            for m3 in groups[3]:
                if not (m2['record_serial']<m3['record_serial'] and m3['replay_counter']>m1['replay_counter'] and m3['nonce']==m1['nonce']):continue
                for m4 in groups[4]:
                    if m3['record_serial']<m4['record_serial'] and m3['replay_counter']==m4['replay_counter']:
                        chosen=[m['record_serial'] for m in (m1,m2,m3,m4)];break
                if chosen:break
            if chosen:break
        if chosen:break
    return dict(messages={str(k):len(v) for k,v in groups.items()},complete_four_way=chosen is not None,
                coherent_record_serials=chosen,mic_verification='not performed; classification only')


def convert(capture,out,target,ap,live=False):
    out.mkdir(parents=True,exist_ok=False);rows,transport=read_stream(capture,live)
    frames=[];eapol=[];rejected=[]
    for r in rows:
        if r['event'] not in ('CSI_DATA','RAW','FRAME'):continue
        if r['event']=='CSI_DATA':
            try:raw=assemble_api_parts(r)
            except ValueError as exc:
                rejected.append(dict(record_serial=r['record_serial'],source_event=r['event'],reason=str(exc)))
                continue
        else:
            if r.get('truncated'):raise ValueError('truncated FRAME record')
            raw=bytes.fromhex(r['raw_hex'])
        try:
            e,_=classify_record(r,target,ap);eapol.append(e)
        except ValueError as exc:
            rejected.append(dict(record_serial=r['record_serial'],source_event=r['event'],reason=str(exc)))
        frames.append((r,raw))
    index=[]
    with (out/'combined_private.pcap').open('xb') as f:
        f.write(struct.pack('<IHHIIII',0xa1b23c4d,2,4,0,0,8192,127))
        for num,(r,raw) in enumerate(frames,1):
            ch=r['channel'];freq=2407+5*ch if ch<=13 else 5000+5*ch
            # Radiotap flags zero: no assertion that FCS is present or absent in API bytes.
            rt=struct.pack('<BBHIBxHHb',0,0,15,0x2a,0,freq,0x80 if ch<=14 else 0x100,r['rssi'])
            ns=r['host_time_ns'];packet=rt+raw
            f.write(struct.pack('<IIII',ns//10**9,ns%10**9,len(packet),len(packet)));f.write(packet)
            h=r['mac_header'];entry={k:r[k] for k in ('record_serial','timestamp','seq_ctrl','format','rssi','event')}
            entry.update(synthetic=bool(r['flags']&16),pcap_frame_number=num,retry=h['retry'],fragment=h['fragment'],more_fragments=h['more_fragments'],amsdu=h['amsdu'])
            if r['event']=='CSI_DATA':entry.update(rx_seq=r['rx_seq'],csi_len=r['csi_len'],csi_copied=r['csi_copied'],csi_sha256=hashlib.sha256(bytes.fromhex(r['csi_hex'])).hexdigest(),valid=r['estimate_valid'],csi_valid=bool(r['csi_valid']),rx_state=r['rx_state'],first_word_invalid=r['first_word_invalid'])
            index.append(entry)
    result=dict(handshake=handshake(eapol),eapol_records=eapol,rejected_eapol=rejected,transport=transport,
                atomic_records=sum(r['event']=='CSI_DATA' for r in rows),live_snapshot=live,
                last_counters=next((r['counters'] for r in reversed(rows) if r['event'] in ('STATS','FINAL','ARMED')),None))
    (out/'frame_index_private.json').write_text(json.dumps(index,indent=2),encoding='utf-8')
    (out/'handshake_private.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--capture',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--target',required=True);p.add_argument('--ap',required=True);p.add_argument('--live',action='store_true');a=p.parse_args()
    r=convert(a.capture,a.output,a.target.lower(),a.ap.lower(),a.live)
    print(json.dumps(dict(handshake=r['handshake'],rejected_eapol=len(r['rejected_eapol']),atomic_records=r['atomic_records'])))
