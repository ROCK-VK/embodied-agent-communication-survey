"""Control only embodied-phase2 compose services; execute/verify real network traffic."""
import json
import os
import subprocess
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT.parent
OUT=ROOT/'结果/网络实验'
PRIVATE=PROJECT/'日志/下一阶段/network'
COMPOSE=['docker','compose','-f',str(ROOT/'compose.yaml')]

def run(args,**kw):
    result=subprocess.run(args,check=True,text=True,encoding='utf-8',errors='replace',**kw)
    return result.stdout

def inside(service,args):
    return COMPOSE+['exec','-T',service,'bash','-lc',args]

def main():
    OUT.mkdir(parents=True,exist_ok=True);PRIVATE.mkdir(parents=True,exist_ok=True)
    protected=[n for n in os.environ.get('EMBODIED_PROTECTED_CONTAINERS','').split(',') if n.strip()]
    baseline=json.loads(run(['docker','inspect',*protected],capture_output=True)) if protected else []
    result=[]
    try:
        # Docker build provenance can change an OCI index even with identical payload layers.
        # Recreate only these dedicated services so inspected image identities match the build.
        run(COMPOSE+['up','-d','--force-recreate','--no-build'])
        run(inside('sender',"until python3 -c 'import xmlrpc.client; assert xmlrpc.client.ServerProxy(\"http://master:11311\").getPid(\"phase2\")[0]==1'; do sleep 0.2; done"),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=25)
        for mode in ('tcp','udp','ros1'):
            profiles=('normal','netem','reconnect') if mode=='tcp' else ('normal','netem')
            for profile in profiles:
                case=mode+'-'+profile;directory=OUT/case;directory.mkdir(exist_ok=True)
                ready=directory/'ready'
                if ready.exists():ready.unlink()
                run(inside('sender','tc qdisc del dev eth0 root 2>/dev/null || true'),stdout=subprocess.DEVNULL)
                # netem affects actual IPv4 traffic in this container, not the host or other projects.
                impairment=profile=='netem'
                if impairment:
                    run(inside('sender','tc qdisc replace dev eth0 root netem delay 25ms 5ms loss 12% rate 512kbit'))
                qdisc=run(inside('sender','tc -s qdisc show dev eth0'),capture_output=True)
                log=(PRIVATE/(case+'.log')).open('w',encoding='utf-8')
                command='source /opt/ros/noetic/setup.bash; python3 /project/扩展调研与模拟/实验/netnode.py receiver --mode '+mode+' --case '+case
                if profile=='reconnect':command+=' --reconnect'
                receiver=subprocess.Popen(inside('receiver',command),stdout=log,stderr=subprocess.STDOUT)
                try:
                    deadline=time.monotonic()+20
                    while not ready.exists():
                        if receiver.poll() is not None:raise RuntimeError('receiver exited: '+case)
                        if time.monotonic()>deadline:raise TimeoutError('receiver startup: '+case)
                        time.sleep(.05)
                    run(inside('sender','source /opt/ros/noetic/setup.bash; python3 /project/扩展调研与模拟/实验/netnode.py sender --mode '+mode+' --case '+case),stdout=log,stderr=subprocess.STDOUT,timeout=120)
                    assert receiver.wait(timeout=15)==0,case
                finally:
                    if receiver.poll() is None:receiver.terminate();receiver.wait(10)
                    log.close()
                qdisc_after=run(inside('sender','tc -s qdisc show dev eth0'),capture_output=True)
                sender=json.loads((directory/'sender.json').read_text(encoding='utf-8'));sink=json.loads((directory/'receiver.json').read_text(encoding='utf-8'))
                expected=set(sender['seqs']);arrived=set(sink['arrived_seqs']);accepted=set(sink['accepted_seqs'])
                assert arrived<=expected and accepted<=arrived
                assert len(arrived)==sink['accepted']+sink['expired']
                assert all(w['spent_with_annotation']<=w['budget'] for w in sender['windows'])
                assert sink['captured_frames']>0 and sink['captured_ethernet_bytes']>0
                if mode=='tcp':assert arrived==expected
                if profile=='normal':assert arrived==expected and not sink['expired']
                if profile=='reconnect':assert sender['application_retries']>=1 and sink['duplicates_discarded']>=1
                result.append({'case':case,'mode':mode,'profile':profile,'sender':sender,'receiver':sink,
                    'network_missing':len(expected-arrived),'missing_seqs':sorted(expected-arrived),'budget_violations':0,
                    'qdisc_before':qdisc,'qdisc_after':qdisc_after,
                    'network_scope':'real Docker bridge between isolated namespaces on same Windows Docker Desktop kernel; netem is synthetic link impairment, not physical wireless'})
                print(json.dumps({'case':case,'sent':len(expected),'arrived':len(arrived),'accepted':len(accepted),'missing':len(expected-arrived),'ethernet_bytes':sink['captured_ethernet_bytes']}),flush=True)
        (OUT/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        own=json.loads(run(['docker','inspect','embodied-phase2-master','embodied-phase2-sender','embodied-phase2-receiver'],capture_output=True))
        (OUT/'environment.json').write_text(json.dumps([{'name':i['Name'],'image':i['Image'],'networks':i['NetworkSettings']['Networks'],
            'cpu_quota_nano':i['HostConfig']['NanoCpus'],'memory_limit':i['HostConfig']['Memory'],'cap_add':i['HostConfig']['CapAdd'],
            'published_ports':i['HostConfig']['PortBindings']} for i in own],indent=2),encoding='utf-8')
        packages=run(inside('sender','dpkg-query -W iproute2; uname -r; tc -V'),capture_output=True)
        (OUT/'network-version.txt').write_text(packages,encoding='utf-8')
    finally:
        subprocess.run(inside('sender','tc qdisc del dev eth0 root 2>/dev/null || true'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        run(COMPOSE+['stop'])
        after=json.loads(run(['docker','inspect',*protected],capture_output=True)) if protected else []
        keys=('Image','Config','HostConfig','Mounts','State')
        checks=[{'name':a['Name'],'unchanged':all(a[k]==b[k] for k in keys)} for a,b in zip(baseline,after)]
        (OUT/'其他项目保护.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
        assert all(c['unchanged'] for c in checks)

if __name__=='__main__':main()
