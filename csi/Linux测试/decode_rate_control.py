"""Privately decode fixed-payload control data using one existing session handshake."""
import argparse,collections,getpass,hashlib,json,pathlib,struct,subprocess
import multimodal_udp as protocol
from direct_csi_extract import handshake_packets

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=pathlib.Path,required=True);p.add_argument('--handshake',type=pathlib.Path,required=True);p.add_argument('--target',required=True);p.add_argument('--tshark',type=pathlib.Path,required=True);p.add_argument('--ssid',required=True);a=p.parse_args()
    cap=a.root/'csi-rate-control-20261110';out=cap/'offline_private';header,hs=handshake_packets(a.handshake,bytes.fromhex(a.target.replace(':','')))
    if not hs:raise ValueError('no handshake')
    combined=out/'pcap_handshake_private.pcap'
    with (cap/'monitor.pcap').open('rb') as src,combined.open('xb') as dst:
        h=src.read(24)
        if h!=header:raise ValueError('pcap format mismatch')
        dst.write(h)
        for sec,usec,b,wire in hs:dst.write(struct.pack('<IIII',sec,usec,len(b),wire));dst.write(b)
        while block:=src.read(1048576):dst.write(block)
    secret=getpass.getpass('Wi-Fi key: ');mapping=json.loads((out/'record_map_private.json').read_text());result={}
    for name,path in [('csi',out/'csi_mpdu_private.pcap'),('pcap',combined)]:
        cmd=[str(a.tshark),'-r',str(path),'-o','wlan.enable_decryption:TRUE','-o','uat:80211_keys:"wpa-pwd","'+secret+':'+a.ssid+'"','-Y','udp.dstport==39001','-T','fields','-E','separator=|','-e','frame.number','-e','udp.payload']
        proc=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace')
        if proc.returncode:raise RuntimeError('tshark failed')
        rows=[];errors=collections.Counter()
        for line in proc.stdout.splitlines():
            try:
                frame,h=line.split('|');meta,data=protocol.unpack(bytes.fromhex(h.replace(':','')))
                if meta['run_id'] not in (2026111021,2026111022,2026111023,2026111024):continue
                if name=='csi':
                    info=mapping[frame]
                    if not info['csi_structural']:raise ValueError('invalid CSI structure')
                else:info={}
                rows.append({**meta,'payload_sha256':hashlib.sha256(data).hexdigest(),'frame':int(frame),**info})
            except (ValueError,KeyError) as exc:errors[type(exc).__name__]+=1
        result[name]={'rows':rows,'errors':dict(errors)}
    with (out/'decoded_all_private.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:{'records':len(v['rows']),'errors':v['errors']} for k,v in result.items()}))
if __name__=='__main__':main()
