"""Actual isolated-container IPv4 transport; kernel netem configured only inside sender."""
import argparse
import collections
import json
import socket
import statistics
import struct
import threading
import time
from pathlib import Path

PORTS={'tcp':9501,'udp':9502,'ros1':0}
CONTROL=9500
def encode(record):return json.dumps(record,separators=(',',':')).encode()
def exact(sock,count):
    data=b''
    while len(data)<count:
        block=sock.recv(count-len(data))
        if not block:raise ConnectionError('peer closed')
        data+=block
    return data

class Capture:
    def __init__(self,mode,case):
        self.stop=threading.Event();self.count=0;self.bytes=0;self.tcp_duplicates=0;self.seen=set();self.protocols=collections.Counter()
        self.peer=socket.gethostbyname('sender');self.mode=mode
        directory=Path('/private')/case;directory.mkdir(parents=True,exist_ok=True)
        self.file=(directory/'receiver-eth0.pcap').open('wb')
        self.file.write(struct.pack('<IHHIIII',0xa1b2c3d4,2,4,0,0,65535,1))
        self.sock=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3));self.sock.bind(('eth0',0));self.sock.settimeout(.1)
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def run(self):
        while not self.stop.is_set():
            try:frame=self.sock.recv(65535)
            except socket.timeout:continue
            if len(frame)<34 or frame[12:14]!=b'\x08\x00':continue
            ip=frame[14:];ihl=(ip[0]&15)*4;proto=ip[9]
            src=socket.inet_ntoa(ip[12:16]);dst=socket.inet_ntoa(ip[16:20])
            if self.peer not in (src,dst) or proto not in (6,17):continue
            transport=ip[ihl:];sport,dport=struct.unpack('!HH',transport[:4])
            if CONTROL in (sport,dport):continue
            if self.mode!='ros1' and PORTS[self.mode] not in (sport,dport):continue
            now=time.time();sec=int(now);usec=int((now-sec)*1e6)
            self.file.write(struct.pack('<IIII',sec,usec,len(frame),len(frame)));self.file.write(frame)
            self.count+=1;self.bytes+=len(frame);self.protocols[str(proto)]+=1
            if proto==6 and len(transport)>=20:
                header=(transport[12]>>4)*4;length=struct.unpack('!H',ip[2:4])[0]-ihl-header
                if length>0:
                    seq=struct.unpack('!I',transport[4:8])[0];key=(src,dst,sport,dport,seq,length)
                    if key in self.seen:self.tcp_duplicates+=1
                    self.seen.add(key)
    def close(self):
        self.stop.set();self.thread.join(2);self.sock.close();self.file.close()
        return {'captured_frames':self.count,'captured_ethernet_bytes':self.bytes,'ip_protocol_counts':dict(self.protocols),
                'observed_duplicate_tcp_segments':self.tcp_duplicates,
                'scope':'receiver eth0, bidirectional matching peer IPv4, excludes control port; ROS1 includes its XMLRPC/TCPROS connection traffic; no Ethernet FCS, no WiFi/physical overhead'}

def receiver(mode,case,reconnect):
    output=Path('/output')/case;output.mkdir(parents=True,exist_ok=True)
    stop=threading.Event();ready=threading.Event();lock=threading.Lock();seen=set();accepted=[];ages=[];duplicates=0;stale=0;arrivals=0
    capture=Capture(mode,case)
    def receive_record(record):
        nonlocal duplicates,stale,arrivals
        with lock:
            arrivals+=1
            if record['seq'] in seen:duplicates+=1;return
            seen.add(record['seq']);age=(time.time_ns()-record['sent_at_ns'])/1e9;ages.append(age)
            if age>.5:stale+=1
            else:accepted.append(record)
    def data_server():
        if mode=='udp':
            sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind(('0.0.0.0',PORTS[mode]));sock.settimeout(.1);ready.set()
            try:
                while not stop.is_set():
                    try:data,_=sock.recvfrom(65535)
                    except socket.timeout:continue
                    length=struct.unpack('!I',data[:4])[0];assert length==len(data)-4
                    receive_record(json.loads(data[4:]))
            finally:sock.close()
        elif mode=='tcp':
            listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);listener.bind(('0.0.0.0',PORTS[mode]));listener.listen();listener.settimeout(.1);ready.set();closed=False
            try:
                while not stop.is_set():
                    try:conn,_=listener.accept()
                    except socket.timeout:continue
                    conn.settimeout(2)
                    with conn:
                        while not stop.is_set():
                            try:length=struct.unpack('!I',exact(conn,4))[0];record=json.loads(exact(conn,length))
                            except (ConnectionError,socket.timeout,OSError):break
                            receive_record(record)
                            if reconnect and not closed and len(seen)>=40:closed=True;break
                            try:conn.sendall(struct.pack('!I',record['seq']))
                            except OSError:break
            finally:listener.close()
        else:
            import rospy
            from std_msgs.msg import String
            rospy.init_node('phase2_receiver',disable_signals=True)
            sub=rospy.Subscriber('/phase2/perception',String,lambda msg:receive_record(json.loads(msg.data)),queue_size=1000)
            ready.set()
            while not stop.wait(.1):pass
            sub.unregister();rospy.signal_shutdown('test completed')
    worker=threading.Thread(target=data_server,daemon=True);worker.start()
    if not ready.wait(15):raise RuntimeError('receiver did not become ready')
    control=socket.socket();control.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);control.bind(('0.0.0.0',CONTROL));control.listen();control.settimeout(30)
    (output/'ready').write_text('ready')
    try:
        connection,_=control.accept()
        with connection:
            assert connection.recv(50)==b'finish'
            time.sleep(2);connection.sendall(b'ok')
    finally:control.close();stop.set();worker.join(5)
    wire=capture.close()
    (output/'received.jsonl').write_text('\n'.join(encode(r).decode() for r in sorted(accepted,key=lambda r:r['seq']))+'\n')
    summary={'case':case,'mode':mode,'arrivals_including_retries':arrivals,'unique_arrived':len(seen),'accepted':len(accepted),
        'duplicates_discarded':duplicates,'expired':stale,'arrived_seqs':sorted(seen),'accepted_seqs':sorted(r['seq'] for r in accepted),
        'age_p50_ms':statistics.median(ages)*1000 if ages else None,
        'age_p95_ms':sorted(ages)[min(len(ages)-1,int(len(ages)*.95))]*1000 if ages else None,
        'shared_clock_scope':'wall clocks share Docker Desktop kernel; no distributed clock synchronization verified',**wire}
    (output/'receiver.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))

def sender(mode,case):
    manifest=json.loads(Path('/project/下一阶段/结果/图像实验/network-input.json').read_text(encoding='utf-8'))
    selected=set(manifest['selected_seqs']);rows=[];windows=[]
    for window in manifest['windows']:
        lo=window['window']*100;block=manifest['stream'][lo:lo+100]
        expanded=[dict(r,sent_at_ns=10**18) for r in block]
        # Recompute complete on-wire application JSON cost, then add separate simulated annotation charge.
        budget=int(sum(4+len(encode(r))+5 for r in expanded)*.25);spent=0
        for record in expanded:
            cost=4+len(encode(record))+5
            if record['seq'] in selected and spent+cost<=budget and len(rows)<120:
                rows.append(record);spent+=cost
        windows.append({'window':window['window'],'budget':budget,'spent_with_annotation':spent})
    retries=0;connections=0;app_bytes=0;attempt_bytes=0;start=time.perf_counter();conn=None
    if mode=='ros1':
        import rospy
        from std_msgs.msg import String
        rospy.init_node('phase2_sender',disable_signals=True);pub=rospy.Publisher('/phase2/perception',String,queue_size=1000)
        deadline=time.monotonic()+10
        while pub.get_num_connections()==0 and time.monotonic()<deadline:time.sleep(.02)
        if not pub.get_num_connections():raise RuntimeError('no ROS1 subscriber')
    elif mode=='udp':conn=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    try:
        for record in rows:
            record['sent_at_ns']=time.time_ns();payload=encode(record);frame=struct.pack('!I',len(payload))+payload
            app_bytes+=len(frame)
            if mode=='ros1':pub.publish(String(data=payload.decode()));attempt_bytes+=len(frame)
            elif mode=='udp':conn.sendto(frame,('receiver',PORTS[mode]));attempt_bytes+=len(frame)
            else:
                for attempt in range(6):
                    try:
                        if conn is None:
                            conn=socket.create_connection(('receiver',PORTS[mode]),timeout=2);conn.settimeout(2);conn.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);connections+=1
                        attempt_bytes+=len(frame);conn.sendall(frame)
                        ack=struct.unpack('!I',exact(conn,4))[0]
                        if ack!=record['seq']:raise RuntimeError('wrong ACK')
                        break
                    except (OSError,ConnectionError):
                        retries+=1
                        if conn:conn.close()
                        conn=None
                        if attempt==5:raise
                else:raise RuntimeError('retry budget exhausted')
            time.sleep(.004)
        time.sleep(.3)
        finish=socket.create_connection(('receiver',CONTROL),timeout=5);finish.settimeout(10)
        with finish:finish.sendall(b'finish');assert finish.recv(20)==b'ok'
    finally:
        if conn:conn.close()
        if mode=='ros1':rospy.signal_shutdown('test completed')
    summary={'case':case,'mode':mode,'selected':len(rows),'seqs':[r['seq'] for r in rows],
        'unique_application_frame_bytes':app_bytes,'application_attempt_frame_bytes':attempt_bytes,
        'simulated_annotation_bytes':len(rows)*5,'windows':windows,'application_retries':retries,'connections':connections,
        'wall_seconds_including_2s_receiver_drain':time.perf_counter()-start}
    output=Path('/output')/case;output.mkdir(parents=True,exist_ok=True);(output/'sender.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('role',choices=['sender','receiver']);parser.add_argument('--mode',choices=PORTS,required=True);parser.add_argument('--case',required=True);parser.add_argument('--reconnect',action='store_true');args=parser.parse_args()
    if args.role=='sender':sender(args.mode,args.case)
    else:receiver(args.mode,args.case,args.reconnect)
