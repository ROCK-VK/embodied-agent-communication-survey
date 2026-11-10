"""Analyze already decrypted packet indexes and radiotap metadata; no keys needed."""
import argparse,collections,csv,hashlib,json,pathlib,statistics,struct,subprocess

def j(path): return json.loads(path.read_text(encoding='utf-8'))
def packets(path,selected):
    with path.open('rb') as f:
        f.read(24);num=0
        while h:=f.read(16):
            if len(h)!=16: raise ValueError('truncated pcap')
            _,_,size,_=struct.unpack('<IIII',h);b=f.read(size);num+=1
            if len(b)!=size:raise ValueError('truncated frame')
            if num in selected: yield num,b[int.from_bytes(b[2:4],'little'):]

def analyze(root,tshark):
    cap=root/'csi-diagnose-20261110';d=cap/'offline_private';sender=root/'sender'
    cs=[j(d/f'direct_r{i}.json') for i in (1,2,3)];pc=[j(d/f'pcap_r{i}.json') for i in (1,2,3)]
    csbytes={n:hashlib.sha256(b).digest() for n,b in packets(d/'csi_mpdu_private.pcap',{x['frame'] for rows in cs for x in rows})}
    cset=set(csbytes.values()); needed={x['frame'] for rows in pc for x in rows}
    direct={n:(hashlib.sha256(b).digest() in cset or hashlib.sha256(b[:-4]).digest() in cset) for n,b in packets(d/'pcap_handshake_private.pcap',needed)}
    fields=['frame.number','frame.len','wlan.fc.type_subtype','wlan.fc.retry','wlan.seq','wlan_radio.data_rate','radiotap.dbm_antsignal','radiotap.vht.mcs.0','radiotap.vht.bw','radiotap.mcs.index','radiotap.ampdu.reference']
    cmd=[str(tshark),'-r',str(d/'pcap_handshake_private.pcap'),'-T','fields','-E','separator=|','-E','occurrence=f']
    for field in fields:cmd+=['-e',field]
    proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',errors='replace'); meta={}
    for line in proc.stdout:
        row=line.rstrip('\n').split('|')
        if len(row)==len(fields) and row[0].isdigit() and int(row[0]) in needed:meta[int(row[0])]=dict(zip(fields,row))
    if proc.wait()!=0:raise RuntimeError('tshark failed')
    if set(meta)!=needed or set(direct)!=needed:raise ValueError('missing pcap frame data')
    all_results=[]
    for ix,(c,p) in enumerate(zip(cs,pc),1):
        send=[json.loads(x) for x in (sender/f'r{ix}/sender_packets.jsonl').read_text().splitlines()]
        cids={x['packet_id'] for x in c};pids={x['packet_id'] for x in p}; byid=collections.defaultdict(list)
        for row in p:byid[row['packet_id']].append(row)
        if any(x['packet_id'] not in pids for x in c):raise ValueError('CSI ID missing from pcap')
        groups={}
        for group,rows in [('matched_attempts',[x for x in p if direct[x['frame']]]),('pcap_only_attempts',[x for x in p if x['packet_id'] not in cids])]:
            groups[group]={'count':len(rows)}
            for field in ('frame.len','wlan.fc.type_subtype','wlan.fc.retry','wlan_radio.data_rate','radiotap.vht.mcs.0','radiotap.vht.bw','radiotap.ampdu.reference'):
                groups[group][field]=dict(collections.Counter((meta[x['frame']][field] or '<absent>') if field!='radiotap.ampdu.reference' else ('present' if meta[x['frame']][field] else '<absent>') for x in rows))
            rss=[int(meta[x['frame']]['radiotap.dbm_antsignal']) for x in rows if meta[x['frame']]['radiotap.dbm_antsignal'].lstrip('-').isdigit()]
            groups[group]['rssi_count']=len(rss);groups[group]['rssi_median']=statistics.median(rss) if rss else None
        t=send[0]['send_mono_ns'];windows=[]
        for w in range(6):
            items=[x for x in send if w*10**10<=x['send_mono_ns']-t<(w+1)*10**10];ids={x['packet_id'] for x in items}; attempts=[x for x in p if x['packet_id'] in ids];rss=[int(meta[x['frame']]['radiotap.dbm_antsignal']) for x in attempts if meta[x['frame']]['radiotap.dbm_antsignal'].lstrip('-').isdigit()]
            windows.append({'start_s':w*10,'sent':len(ids),'csi_ids':len(ids&cids),'pcap_ids':len(ids&pids),'neither':len(ids-(cids|pids)),'pcap_attempts':len(attempts),'retry_attempts':sum(str(x['retry']).lower() in ('1','true') for x in attempts),'rssi_median':statistics.median(rss) if rss else None,'rates':dict(collections.Counter(meta[x['frame']]['wlan_radio.data_rate'] or '<absent>' for x in attempts)),'mcs':dict(collections.Counter(meta[x['frame']]['radiotap.vht.mcs.0'] or '<absent>' for x in attempts))})
        missing=[x['packet_id'] not in cids|pids for x in send];runs=[];start=None
        for n,miss in enumerate(missing+[False]):
            if miss and start is None:start=n
            elif not miss and start is not None:runs.append(n-start);start=None
        all_results.append({'round':ix,'groups':groups,'windows':windows,'neither_runs':{'count':len(runs),'max':max(runs,default=0),'ge5':sum(x>=5 for x in runs),'length_distribution':dict(collections.Counter(runs))}})
    return all_results

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=pathlib.Path,required=True);p.add_argument('--tshark',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
    result=analyze(a.root,a.tshark)
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
