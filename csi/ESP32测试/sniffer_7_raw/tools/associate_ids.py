"""Preserve packet-ID/MPDU/CSI multiplicity in offline evidence, without cryptography."""
import argparse
import collections
import json
from pathlib import Path
from raw7 import match_key


def associate(extracted, records, sender=(), receiver=()):
    by_serial={r['record_serial']:r for r in records}
    csi=collections.defaultdict(list)
    for r in records:
        if r['event']=='CSI':csi[match_key(r)].append(r)
    send={(r['run_id'],r['packet_id']):r for r in sender if r.get('event')=='SEND'}
    recv=collections.defaultdict(list)
    for r in receiver:
        if r.get('status') in ('valid','duplicate'):recv[(r['run_id'],r['packet_id'])].append(r)
    out=[]
    for p in extracted['valid_ids']:
        index=p.get('raw_frame')
        if not index:continue
        f=by_serial[index['record_serial']];h=f['mac_header'];key=(p['run_id'],p['packet_id'])
        out.append(dict(run_id=key[0],packet_id=key[1],sender_time=p.get('sender_mono_ns'),
                        sender_log=send.get(key),receiver_times=[r.get('recv_mono_ns') for r in recv[key]],
                        frame_record_serial=f['record_serial'],frame_timestamp=f['timestamp'],
                        seq_ctrl=f['seq_ctrl'],retry=h['retry'],frag=h['fragment'],
                        phy_format=f['format'],channel=f['channel'],rssi=f['rssi'],
                        candidate_csi=[dict(record_serial=c['record_serial'],timestamp=c['timestamp'],
                                            format=c['format'],len=c['original_len'],raw=c['raw_hex'],
                                            valid=c['estimate_valid'],rx_state=c['rx_state'],
                                            first_word_invalid=c['first_word_invalid']) for c in csi[match_key(f)]],
                        mapping_scope=p['reassembly_scope'],
                        complete_fragment_ancestry_verified=False))
    return out


def jsonl(p):return [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines()] if p else []


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--extracted',type=Path,required=True)
    p.add_argument('--records',type=Path,required=True);p.add_argument('--sender',type=Path)
    p.add_argument('--receiver',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();out=associate(json.loads(a.extracted.read_text(encoding='utf-8')),jsonl(a.records),jsonl(a.sender),jsonl(a.receiver))
    with a.output.open('x',encoding='utf-8') as f:json.dump(out,f,indent=2)
    print(json.dumps(dict(association_rows=len(out),complete_fragment_ancestry_verified=False)))
