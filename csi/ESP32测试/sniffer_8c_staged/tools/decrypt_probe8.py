"""Offline tshark decryption using a pre-existing private key profile.

No password CLI option; never prints keys or decrypted bytes. Per-frame output is
private. Ambiguous fragmented/A-MSDU mappings are kept but excluded from strict PoC.
"""
import argparse,csv,json,subprocess
from pathlib import Path
from udp_probe_protocol import decode_packet,PacketError


def associate(fields,index,sent,received,run_id,port):
    mapping={str(r['pcap_frame_number']):r for r in index}
    keys=lambda items:{(r['run_id'],r['packet_id'],r['sender_mono_ns']) for r in items if 'sender_mono_ns' in r}
    sk=keys([r for r in sent if r.get('event')=='SEND']);rk=keys([r for r in received if r.get('status') in ('valid','duplicate')])
    matched=[];invalid=foreign=csid=decrypted=0
    for f in fields:
        # frame, protected, llc.type, ip.version, udp.dstport, udp.payload, CCMP PN
        num,prot,llc,ip,ports,payloads,pn=(f+['']*7)[:7]
        m=mapping.get(num)
        if not m or m['event']!='CSI_DATA':continue
        if prot.lower() not in ('1','true'):continue
        if llc or ip:decrypted+=1
        ps=ports.split('|')
        for i,value in enumerate(payloads.split('|')):
            if not value:continue
            if len(ps)!=len(payloads.split('|')) or ps[i]!=str(port):continue
            try:b=bytes.fromhex(value.replace(':',''))
            except ValueError:invalid+=1;continue
            if not b.startswith(b'CSID'):continue
            csid+=1
            try:p=decode_packet(b)
            except PacketError:invalid+=1;continue
            if p['run_id']!=run_id or not 1<=p['packet_id']<=20:foreign+=1;continue
            k=(p['run_id'],p['packet_id'],p['sender_mono_ns'])
            strict=(k in sk and k in rk and m.get('valid')==1 and m.get('rx_state')==0 and
                    m.get('first_word_invalid')==0 and not (m['fragment'] or m['more_fragments'] or m['amsdu']))
            matched.append(dict(**p,**m,ccmp_pn=pn,receiver_confirmed=k in rk,sender_confirmed=k in sk,
                                strict_atomic_association=strict,crc_and_test_pattern_valid=True))
    strict=[r for r in matched if r['strict_atomic_association']]
    return dict(decrypted_target_ip_or_llc_frames=decrypted,csid_payloads=csid,invalid_csid_payloads=invalid,
                foreign_run_or_id=foreign,observations=matched,strict_observation_count=len(strict),
                strict_unique_packet_ids=sorted({r['packet_id'] for r in strict}),minimum_poc_passed=bool(strict),
                limitations='No inference of one UDP per MPDU/CSI; reassembly ancestry excluded from strict results')


def main():
    p=argparse.ArgumentParser();p.add_argument('--tshark',type=Path,required=True);p.add_argument('--conversion',type=Path,required=True)
    p.add_argument('--profile',required=True);p.add_argument('--sender-log',type=Path,required=True);p.add_argument('--receiver-log',type=Path,required=True)
    p.add_argument('--run-id',type=lambda x:int(x,0),required=True);p.add_argument('--port',type=int,default=39001);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();h=json.loads((a.conversion/'handshake_private.json').read_text(encoding='utf-8'))
    index=json.loads((a.conversion/'frame_index_private.json').read_text(encoding='utf-8'))
    if any(r.get('synthetic') for r in index):raise RuntimeError('Synthetic engineering records cannot be used as real WPA2 evidence')
    if not h['handshake']['complete_four_way']:raise RuntimeError('A: no coherent complete four-way; do not decrypt/send UDP')
    c=h['last_counters']
    if not c or any(c.get(k,0) for k in ('raw_drop','csi_drop','raw_truncated','csi_truncated','payload_truncated','write_errors')) or c.get('min_free_heap',0)<16384:
        raise RuntimeError('F: resource gate not passed')
    a.output.mkdir(parents=True,exist_ok=False)
    cmd=[str(a.tshark),'-n','-2','-C',a.profile,'-r',str(a.conversion/'combined_private.pcap'),
         '-o','wlan.enable_decryption:TRUE','-o','wlan.ignore_wep:No','-Y','wlan.fc.protected',
         '-T','fields','-E','separator=/t','-E','occurrence=a','-E','aggregator=|']
    for field in ('frame.number','wlan.fc.protected','llc.type','ip.version','udp.dstport','udp.payload','wlan.ccmp.extiv'):cmd+=['-e',field]
    proc=subprocess.run(cmd,check=True,capture_output=True,text=True,encoding='utf-8')
    (a.output/'decrypted_private.tsv').write_text(proc.stdout,encoding='utf-8')
    read=lambda path:list(map(json.loads,path.read_text(encoding='utf-8').splitlines()))
    result=associate(list(csv.reader(proc.stdout.splitlines(),delimiter='\t')),
                     json.loads((a.conversion/'frame_index_private.json').read_text(encoding='utf-8')),
                     read(a.sender_log),read(a.receiver_log),a.run_id,a.port)
    (a.output/'association_private.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('observations',)}))


if __name__=='__main__':main()
