"""Extract validated CSID IDs from offline tshark UDP fields; no WPA cryptography.

Use a private Wireshark profile for keys; no password/PSK command-line option.
Frame numbers are mapped back through frame_index.json; multiplicity is retained.
"""
import argparse
import csv
import json
import subprocess
from pathlib import Path
from udp_probe_protocol import decode_packet, PacketError


def extract(tshark,pcap,index,profile=None):
    cmd=[str(tshark),'-n','-2','-r',str(pcap),'-o','wlan.enable_decryption:TRUE']
    if profile:cmd+=['-C',profile]
    cmd+=['-Y','udp','-T','fields','-E','separator=/t','-E','occurrence=a','-E','aggregator=|',
          '-e','frame.number','-e','udp.payload','-e','wlan.seq','-e','wlan.frag','-e','wlan.fc.retry']
    proc=subprocess.run(cmd,check=True,capture_output=True,text=True,encoding='utf-8',errors='replace')
    mapping={str(r['pcap_frame_number']):r for r in index};out=[];invalid=0
    for fields in csv.reader(proc.stdout.splitlines(),delimiter='\t'):
        if len(fields)<2:continue
        for value in fields[1].split('|'):
            try:payload=bytes.fromhex(value.replace(':',''))
            except ValueError:continue
            if not payload.startswith(b'CSID'):continue
            try:packet=decode_packet(payload)
            except PacketError:invalid+=1;continue
            out.append(dict(**packet,pcap_frame_number=int(fields[0]),
                            raw_frame=mapping.get(fields[0]),
                            reassembly_scope='This frame carries/displays the dissected UDP; fragmented/A-MSDU component ancestry still requires explicit Wireshark reassembly analysis, never infer one UDP one MPDU.'))
    return dict(valid_ids=out,invalid_csid_payloads=invalid,keys_supplied_by_profile=bool(profile))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--tshark',type=Path,required=True)
    p.add_argument('--pcap',type=Path,required=True);p.add_argument('--index',type=Path,required=True)
    p.add_argument('--profile');p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=extract(a.tshark,a.pcap,json.loads(a.index.read_text(encoding='utf-8')),a.profile)
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(valid_count=len(result['valid_ids']),invalid=result['invalid_csid_payloads'])))
