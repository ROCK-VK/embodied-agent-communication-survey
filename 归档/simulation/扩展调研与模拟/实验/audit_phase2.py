"""Cross-check data/transport/training/task persistence against independent source artifacts."""
import ast
import csv
import hashlib
import json
import socket
import sqlite3
import struct
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.datasets import load_digits
from image_selection import select
ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT.parent
checks=[]
def check(name,condition):
    assert condition,name
    checks.append(name)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    data=ROOT/'结果/图像实验'
    runs=pd.read_csv(data/'runs.csv');windows=pd.read_csv(data/'window-budgets.csv')
    check('480 unique public-image trials',len(runs)==480 and not runs.duplicated(['scenario','seed','ratio','strategy','learning_work']).any())
    check('exact additional learner work',runs.processed.eq(runs.learning_work).all())
    check('finite accuracy/F1 and valid annotation accounting',np.isfinite(runs[['accuracy','macro_f1']].to_numpy()).all() and runs.macro_f1.between(0,1).all() and runs.annotation_bytes.eq(runs.selected*5).all())
    check('all window byte budgets',windows.spent.le(windows.budget).all() and runs.budget_violations.eq(0).all())
    for key,group in windows.groupby(['scenario','seed','ratio','strategy']):
        part=runs[(runs.scenario==key[0])&(runs.seed==key[1])&(runs.ratio==key[2])&(runs.strategy==key[3])]
        assert len(part)==2 and part.selected_bytes.eq(group.spent.sum()).all()
    checks.append('independent per-window/total-byte conservation')
    digits=load_digits();expected_hash=hashlib.sha256(digits.data.tobytes()+digits.target.tobytes()).hexdigest()
    splits=json.loads((data/'split-manifest.json').read_text(encoding='utf-8'))
    for split in splits:
        warm,pool,test=(set(split[k]) for k in ('warm_ids','pool_ids','test_ids'))
        assert not(warm&pool or warm&test or pool&test) and len(warm|pool|test)==1797
        assert set(split['stream_source_ids'])<=pool and split['dataset_sha256']==expected_hash
    checks.append('all 15 source-ID holdouts disjoint before repetition')
    metadata=json.loads((data/'metadata.json').read_text(encoding='utf-8'))
    check('config hash and real aggregate resource evidence',metadata['config_sha256']==sha(ROOT/'实验/image-config.json') and metadata['cpu_seconds']>0 and metadata['wall_seconds']>0 and metadata['peak_process_working_set_mib']>0)
    code=ast.parse((ROOT/'实验/image_selection.py').read_text(encoding='utf-8'))
    selector=next(n for n in code.body if isinstance(n,ast.FunctionDef) and n.name=='select')
    names={n.id for n in ast.walk(selector) if isinstance(n,ast.Name)}
    check('selection function has no label/test inputs',not(names&{'labels','y','ty','test_x','test_y','truth'}))
    manifest=json.loads((data/'network-input.json').read_text(encoding='utf-8'));records=manifest['stream']
    check('sender contract excludes truth labels',all(not({'label','truth','annotation'}&set(r)) for r in records))
    features=np.array([r['vision'] for r in records])/16
    costs=np.array([4+len(json.dumps(r,separators=(',',':')).encode())+5 for r in records])
    chosen,_=select(records,features,costs,.25,'diverse_cost',11)
    check('selected replay agrees without labels/test',chosen.tolist()==manifest['selected_seqs'])
    proxy=json.loads((ROOT/'结果/代理目标精确解.json').read_text(encoding='utf-8'))
    check('exact proxy solver independently enumerated',len(proxy['cases'])==3 and all(c['exhaustive_verified'] and c['greedy_proxy_value']<=c['optimal_proxy_value'] for c in proxy['cases']))
    network=ROOT/'结果/网络实验';cases=json.loads((network/'summary.json').read_text(encoding='utf-8'));assert len(cases)==7
    training=pd.read_csv(network/'receiver-training.csv').set_index('case')
    environment=json.loads((network/'environment.json').read_text(encoding='utf-8'))
    sender=next(e for e in environment if e['name']=='/embodied-phase2-sender')
    receiver=next(e for e in environment if e['name']=='/embodied-phase2-receiver')
    sender_ip=next(iter(sender['networks'].values()))['IPAddress']
    receiver_ip=next(iter(receiver['networks'].values()))['IPAddress']
    check('different real network namespaces/IPs and no published ports',sender_ip!=receiver_ip and all(not e['published_ports'] for e in environment))
    for case in cases:
        name=case['case'];tx=case['sender'];rx=case['receiver']
        arrived=set(rx['arrived_seqs']);accepted=set(rx['accepted_seqs']);sent=set(tx['seqs'])
        assert arrived<=sent and accepted<=arrived and len(arrived)==rx['accepted']+rx['expired']
        assert len(sent-arrived)==case['network_missing']
        assert rx['duplicates_discarded']==rx['arrivals_including_retries']-rx['unique_arrived']
        assert all(w['spent_with_annotation']<=w['budget'] for w in tx['windows'])
        received=network/name/'received.jsonl'
        rows=[json.loads(line) for line in received.read_text(encoding='utf-8').splitlines() if line.strip()]
        assert {r['seq'] for r in rows}==accepted and len(rows)==rx['accepted']
        assert training.loc[name,'actual_accepted']==len(rows) and training.loc[name,'received_sha256']==sha(received)
        assert training.loc[name,'truth_source_sha256']==sha(data/'network-truth.npz')
        # Independently read actual PCAP records and verify only this isolated peer pair was captured.
        raw=(PROJECT/'日志/下一阶段/network'/name/'receiver-eth0.pcap').read_bytes()
        assert struct.unpack('<I',raw[:4])[0]==0xa1b2c3d4
        pos=24;count=0;total=0
        while pos<len(raw):
            _,_,length,original=struct.unpack('<IIII',raw[pos:pos+16]);pos+=16
            frame=raw[pos:pos+length];pos+=length;assert len(frame)==length==original
            assert frame[12:14]==b'\x08\x00'
            ip=frame[14:];source=socket.inet_ntoa(ip[12:16]);destination=socket.inet_ntoa(ip[16:20])
            assert {source,destination}=={sender_ip,receiver_ip}
            count+=1;total+=length
        assert count==rx['captured_frames'] and total==rx['captured_ethernet_bytes']
    checks.extend(['all seven send/receive/TTL/duplicate/budget conservation checks','actual accepted files match receiver training inputs','private PCAP sizes and peer isolation independently parsed'])
    a2a=json.loads((ROOT/'结果/A2A整合/summary.json').read_text(encoding='utf-8'))
    check('all eleven live A2A checks',len(a2a['checks'])==11 and all(a2a['checks'].values()))
    evidence=a2a['artifact']['analysis'];case=evidence['case']
    actual_digest=hashlib.sha256((network/case/'receiver.json').read_bytes()+(network/'receiver-training.csv').read_bytes()).hexdigest()
    check('A2A artifact bound to actual receiver and training evidence',evidence['evidence_sha256']==actual_digest and abs(evidence['macro_f1']-training.loc[case,'macro_f1'])<1e-12)
    private=PROJECT/a2a['private_database_directory']
    with sqlite3.connect(private/'business-cache.sqlite') as db:count=db.execute('SELECT COUNT(*) FROM results').fetchone()[0]
    check('persistent application cache has exactly two business results',count==2)
    for role in ('analysis','coordinator'):
        with sqlite3.connect(private/(role+'-tasks.sqlite')) as db:
            states=[json.loads(row[0])['state'] for row in db.execute('SELECT status FROM tasks')]
        assert 'TASK_STATE_COMPLETED' in states
    checks.append('both official TaskStores persist completed tasks on disk')
    profiles=json.loads((ROOT/'结果/设备假设核验.json').read_text(encoding='utf-8'))
    check('hypothetical inventories explicitly marked and negative rejected',len(profiles)==3 and not profiles[-1]['validation']['consistent'] and all('mock' in p['profile']['status'] for p in profiles))
    docs=json.loads((ROOT/'结果/宇树官方资料核验.json').read_text(encoding='utf-8'))
    check('all seven official source snapshot hashes',len(docs)==7 and all(sha(PROJECT/d['local_snapshot'])==d['sha256'] for d in docs))
    module=(PROJECT/'日志/下一阶段/module_update.txt').read_text(encoding='utf-8')
    check('official dock source really read',all(s in module for s in ('192.168.123.18','Jetpack5.1.1','Jetson Orin NX')))
    protection=json.loads((network/'其他项目保护.json').read_text(encoding='utf-8'))
    check('other projects unchanged',all(c['unchanged'] for c in protection))
    containers=json.loads(subprocess.check_output(['docker','inspect','embodied-phase2-master','embodied-phase2-sender','embodied-phase2-receiver'],text=True,encoding='utf-8'))
    check('phase2 containers stopped',all(not c['State']['Running'] for c in containers))
    files=[]
    for folder in (ROOT/'实验',ROOT/'环境'):
        if not folder.exists():continue
        for path in sorted(folder.iterdir()):
            if path.is_file():files.append({'path':path.relative_to(ROOT).as_posix(),'sha256':sha(path)})
    for path in (ROOT/'compose.yaml',ROOT/'Dockerfile.network',ROOT/'复现下一阶段.ps1'):
        if path.exists():files.append({'path':path.relative_to(ROOT).as_posix(),'sha256':sha(path)})
    result={'status':'passed','checks':checks,'check_count':len(checks),'source_files':files,
        'scope':'local public-image, actual isolated Docker network and loopback A2A verification; not physical robot validation',
        'private_artifacts_required_for_audit':True}
    (ROOT/'结果/综合审计.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'status':'passed','checks':len(checks)}))

if __name__=='__main__':main()
