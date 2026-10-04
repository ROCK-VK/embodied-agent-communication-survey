"""Four actual ROS1 processes; bounded queues, byte windows, explicit injected faults."""
import argparse
import collections
import json
import os
import random
import signal
import subprocess
import sys
import threading
import time
import xmlrpc.client
from pathlib import Path

CASES = {
    "normal":dict(n=90,hz=60,ratio=.5,window=15,ttl=1.0,worker_delay=0,queue=8,drop=0,delay=0,pause=0),
    "pause":dict(n=90,hz=60,ratio=.5,window=15,ttl=1.0,worker_delay=0,queue=8,drop=0,delay=0,pause=.7),
    "slow_receiver":dict(n=90,hz=60,ratio=1.,window=15,ttl=.15,worker_delay=.08,queue=4,drop=0,delay=0,pause=0),
    "injected_delay":dict(n=60,hz=60,ratio=.5,window=15,ttl=.1,worker_delay=0,queue=8,drop=0,delay=.06,pause=0),
    "injected_loss":dict(n=90,hz=60,ratio=.5,window=15,ttl=1.0,worker_delay=0,queue=8,drop=.35,delay=0,pause=0),
}
STOP = threading.Event()

def serialize(record):
    return json.dumps(record,separators=(",",":"))

def start_node(role,case):
    import rospy
    from std_msgs.msg import String
    rospy.init_node(role+"_"+case,disable_signals=True)
    for sig in (signal.SIGTERM,signal.SIGINT):
        signal.signal(sig,lambda *_:STOP.set())
    pub=rospy.Publisher("/demo/events",String,queue_size=1000)
    def event(kind,**fields):
        pub.publish(String(data=serialize(dict(node=role,event=kind,at=time.monotonic(),**fields))))
    deadline=time.monotonic()+10
    if role!="logger":
        while pub.get_num_connections()==0 and time.monotonic()<deadline:
            time.sleep(.05)
    return rospy,String,event

def logger(case,config,output):
    rospy,String,event=start_node("logger",case)
    last=[None]; active=[False]; alerted=[False]
    lock=threading.Lock()
    output.mkdir(parents=True,exist_ok=True)
    with (output/"events.jsonl").open("w",encoding="utf-8") as stream:
        def log(msg):
            record=json.loads(msg.data)
            if record["event"]=="source_done":active[0]=False
            with lock:
                stream.write(serialize(record)+"\n");stream.flush()
        def saw_source(msg):
            last[0]=time.monotonic();active[0]=True;alerted[0]=False
        events=rospy.Subscriber("/demo/events",String,log,queue_size=2000)
        source=rospy.Subscriber("/demo/perception",String,saw_source,queue_size=1000)
        while not STOP.wait(.02):
            if active[0] and last[0] is not None and not alerted[0] and time.monotonic()-last[0]>.35:
                event("source_gap",gap_seconds=time.monotonic()-last[0]);alerted[0]=True
        events.unregister();source.unregister()
    rospy.signal_shutdown("finished")

def source(case,config,output):
    rospy,String,event=start_node("perception_source",case)
    pub=rospy.Publisher("/demo/perception",String,queue_size=1000)
    deadline=time.monotonic()+10
    while pub.get_num_connections()<2 and time.monotonic()<deadline:
        time.sleep(.05)
    if pub.get_num_connections()<2:raise RuntimeError("selector/logger not connected")
    original=Path("/project/结果/数据实验/redundant-stream.jsonl").read_text(encoding="utf-8").splitlines()
    for i in range(config["n"]):
        if STOP.is_set():break
        if i==config["n"]//2 and config["pause"]:
            event("pause_begin",pause_seconds=config["pause"])
            time.sleep(config["pause"])
        record=json.loads(original[i]);record["collected_at"]=time.monotonic()
        for _ in range(5):
            size=len(serialize(record).encode("utf-8"))
            if record["payload_bytes"]==size:break
            record["payload_bytes"]=size
        assert len(serialize(record).encode("utf-8"))==record["payload_bytes"]
        pub.publish(String(data=serialize(record)))
        event("source_sent",seq=i,payload_bytes=size)
        time.sleep(1/config["hz"])
    event("source_done",count=config["n"])
    time.sleep(.2);rospy.signal_shutdown("source complete")

def selector(case,config,output):
    rospy,String,event=start_node("selector",case)
    pub=rospy.Publisher("/demo/selected",String,queue_size=1000)
    incoming=collections.deque();lock=threading.Lock();rng=random.Random(42)
    def receive(msg):
        with lock:incoming.append(json.loads(msg.data))
    sub=rospy.Subscriber("/demo/perception",String,receive,queue_size=1000)
    block=[];window=0
    def flush():
        nonlocal window
        if not block:return
        # ROS String is 4-byte length + UTF8 JSON; excludes TCPROS framing/network headers.
        budget=int(sum(len(serialize(r).encode())+4 for r in block)*config["ratio"])
        used=0;chosen=[]
        for r in sorted(block,key=lambda r:r["confidence"]):
            size=len(serialize(r).encode())+4
            if used+size<=budget:
                used+=size;chosen.append(r)
            else:event("budget_drop",seq=r["seq"],window=window)
        assert used<=budget
        event("window_budget",window=window,candidates=len(block),selected=len(chosen),budget=budget,selected_bytes=used)
        for r in sorted(chosen,key=lambda r:r["seq"]):
            event("selected",seq=r["seq"],window=window)
            if rng.random()<config["drop"]:
                event("injected_loss",seq=r["seq"]);continue
            if config["delay"]:time.sleep(config["delay"])
            pub.publish(String(data=serialize(r)));event("forwarded",seq=r["seq"],window=window)
        block.clear();window+=1
    idle_since=time.monotonic()
    while not STOP.is_set():
        with lock:item=incoming.popleft() if incoming else None
        if item is None:
            if block and time.monotonic()-idle_since>.15:flush()
            time.sleep(.005);continue
        idle_since=time.monotonic();block.append(item)
        event("selector_received",seq=item["seq"])
        if len(block)>=config["window"]:flush()
    flush();sub.unregister();time.sleep(.1);rospy.signal_shutdown("selector complete")

def receiver(case,config,output):
    rospy,String,event=start_node("receiver",case)
    queue=collections.deque();lock=threading.Lock();accepted=[]
    def receive(msg):
        record=json.loads(msg.data);event("receiver_arrival",seq=record["seq"])
        with lock:
            if len(queue)>=config["queue"]:
                old=queue.popleft();event("queue_drop",seq=old["seq"])
            queue.append(record)
    sub=rospy.Subscriber("/demo/selected",String,receive,queue_size=1000)
    while not STOP.is_set():
        with lock:record=queue.popleft() if queue else None
        if record is None:time.sleep(.005);continue
        if config["worker_delay"]:time.sleep(config["worker_delay"])
        age=time.monotonic()-record["collected_at"]
        if age>config["ttl"]:event("stale_drop",seq=record["seq"],age_seconds=age)
        else:
            accepted.append(record);event("accepted",seq=record["seq"],age_seconds=age)
    with lock:
        for record in queue:event("shutdown_drop",seq=record["seq"])
    (output/"received.jsonl").write_text("\n".join(serialize(r) for r in accepted)+("\n" if accepted else ""),encoding="utf-8")
    sub.unregister();time.sleep(.1);rospy.signal_shutdown("receiver complete")

def run_suite():
    base=Path("/workspaces/catkin_ws/experiment-results/ros1")
    base.mkdir(parents=True,exist_ok=True)
    master=subprocess.Popen(["roscore"],stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,start_new_session=True)
    children=[]
    def stop(proc):
        if proc.poll() is None:
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=8)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
    try:
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            try:
                if xmlrpc.client.ServerProxy("http://127.0.0.1:11311").getUri("suite")[0]==1:break
            except (OSError,xmlrpc.client.Error):time.sleep(.1)
        else:raise RuntimeError("roscore unavailable")
        summaries=[]
        for case,config in CASES.items():
            output=base/case;output.mkdir(exist_ok=True)
            handles=[];procs={}
            for role in ("logger","selector","receiver","source"):
                handle=(output/f"{role}.log").open("w");handles.append(handle)
                proc=subprocess.Popen([sys.executable,__file__,"--role",role,"--case",case,"--output",str(output)],
                    stdout=handle,stderr=subprocess.STDOUT,start_new_session=True)
                children.append(proc);procs[role]=proc
                time.sleep(.2)
            procs["source"].wait(timeout=20)
            assert procs["source"].returncode==0,(case,"source failed")
            time.sleep(max(1.2,config["n"]*config["ratio"]*config["delay"]+1))
            stop(procs["selector"]);time.sleep(.2);stop(procs["receiver"]);time.sleep(.2);stop(procs["logger"])
            for role,proc in procs.items():
                assert proc.returncode==0,(case,role,proc.returncode)
            for handle in handles:handle.close()
            events=[json.loads(line) for line in (output/"events.jsonl").read_text().splitlines()]
            counts=collections.Counter(e["event"] for e in events)
            sequences=lambda kind:{e["seq"] for e in events if e["event"]==kind}
            forwarded=sequences("forwarded");arrivals=sequences("receiver_arrival")
            assert sequences("source_sent")==sequences("selector_received"),(case,"source/selector missing")
            assert forwarded==arrivals,(case,"unexplained transport missing")
            assert sequences("selected")==forwarded|sequences("injected_loss")
            assert arrivals==sequences("accepted")|sequences("queue_drop")|sequences("stale_drop")|sequences("shutdown_drop")
            windows=[e for e in events if e["event"]=="window_budget"]
            assert all(e["selected_bytes"]<=e["budget"] for e in windows)
            ages=[e["age_seconds"] for e in events if e["event"]=="accepted"]
            summary=dict(case=case,config=config,counts=dict(counts),budget_violations=0,
                         unexplained_receiver_missing=len(forwarded-arrivals),
                         max_accepted_age_seconds=max(ages,default=None),
                         scope="Real local TCPROS; faults deliberately injected in application, not wireless loss")
            if case=="normal":assert counts["accepted"]>0 and counts["stale_drop"]==0
            if case=="pause":assert counts["source_gap"]>0
            if case=="slow_receiver":assert counts["queue_drop"]>0 and counts["stale_drop"]>0
            if case=="injected_delay":assert counts["stale_drop"]>0
            if case=="injected_loss":assert counts["injected_loss"]>0
            (output/"summary.json").write_text(json.dumps(summary,indent=2))
            summaries.append(summary);print(json.dumps(summary),flush=True)
        (base/"summary.json").write_text(json.dumps(summaries,indent=2))
    finally:
        for child in children:stop(child)
        stop(master)

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--role",default="suite")
    parser.add_argument("--case",choices=CASES);parser.add_argument("--output")
    args=parser.parse_args()
    if args.role=="suite":run_suite()
    else:globals()[args.role](args.case,CASES[args.case],Path(args.output))
