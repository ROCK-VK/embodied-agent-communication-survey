"""Future on-device read-only DDS diagnostic. Not executed by offline analysis.

Subscribes only; does not send robot control commands or change services.
"""
import argparse
import json
import pathlib
import threading
import time


def clock():
    return {'wall_ns':time.time_ns(),'monotonic_ns':time.monotonic_ns()}


def make_callback(topic, counts, rows, lock):
    def callback(msg):
        received=clock()
        with lock: counts[topic]['callbacks']+=1
        try:
            stamp=getattr(msg,'stamp',None)
            result={'topic':topic,'receipt':received,
                    'stamp':None if stamp is None else {'sec':int(stamp.sec),'nanosec':int(stamp.nanosec),'domain':'unknown'},
                    'position':None if not hasattr(msg,'position') else list(msg.position),
                    'velocity':None if not hasattr(msg,'velocity') else list(msg.velocity),
                    'mode':None if not hasattr(msg,'mode') else int(msg.mode),
                    'tick':None if not hasattr(msg,'tick') else int(msg.tick),
                    'coordinate_frame':'unknown','units':'unknown'}
            with lock:
                counts[topic]['parsed']+=1
                if len(rows)<300: rows.append(result)
        except Exception as exc:
            with lock:
                counts[topic]['callback_errors']+=1
                if len(rows)<300: rows.append({'topic':topic,'receipt':received,'error_type':type(exc).__name__,'error':str(exc)})
    return callback


def main():
    p=argparse.ArgumentParser();p.add_argument('--interface',required=True);p.add_argument('--output',type=pathlib.Path,required=True)
    p.add_argument('--domain',type=int,default=0);p.add_argument('--seconds',type=int,default=15);a=p.parse_args()
    if not 1<=a.seconds<=60: p.error('seconds must be 1..60')
    if a.output.exists(): p.error('output already exists')
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize,ChannelSubscriber
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_,LowState_
    topics={'rt/lowstate':LowState_,'rt/sportmodestate':SportModeState_,'rt/lf/sportmodestate':SportModeState_}
    counts={t:{'callbacks':0,'parsed':0,'callback_errors':0,'init_error':None} for t in topics};rows=[];lock=threading.Lock();subs=[]
    start=clock(); ChannelFactoryInitialize(a.domain,a.interface)
    for topic,kind in topics.items():
        try:
            sub=ChannelSubscriber(topic,kind);sub.Init(make_callback(topic,counts,rows,lock),10);subs.append(sub)
        except Exception as exc: counts[topic]['init_error']={'type':type(exc).__name__,'message':str(exc)}
    time.sleep(a.seconds)
    with lock:
        result={'start':start,'end':clock(),'domain':a.domain,'interface':a.interface,'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'clock_relation':'separate wall and monotonic values; no cross-device synchronization implied',
                'counts':counts,'samples':rows,'sample_limit':300}
        with a.output.open('x',encoding='utf-8') as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'counts':counts,'sample_limit':300}))


if __name__=='__main__': main()
