"""Bounded UDP transfer with sample/chunk/packet provenance and CRC."""
import argparse,hashlib,json,math,pathlib,socket,struct,time,zlib

HEAD=struct.Struct('<4sBBHIIQHH'); CHUNK=struct.Struct('<IIIHHI32s'); BLOCK=400
MAX_SAMPLE_BYTES=64*1024*1024
def pack(run,pid,mono,sample,kind,idx,count,total,digest,data):
 body=CHUNK.pack(sample,idx,count,kind,0,total,digest)+data
 p=HEAD.pack(b'CSID',1,28,0,run,pid,mono,len(body),0)+body
 return p+struct.pack('<I',zlib.crc32(p)&0xffffffff)
def unpack(p):
 if len(p)<HEAD.size+CHUNK.size+4:raise ValueError('short')
 magic,ver,hlen,flags,run,pid,mono,length,res=HEAD.unpack_from(p)
 if magic!=b'CSID' or ver!=1 or hlen!=28 or flags or res or len(p)!=32+length:raise ValueError('header')
 if zlib.crc32(p[:-4])&0xffffffff!=struct.unpack_from('<I',p,len(p)-4)[0]:raise ValueError('crc')
 sample,idx,count,kind,res,total,digest=CHUNK.unpack_from(p,HEAD.size);data=p[HEAD.size+CHUNK.size:-4]
 if res or not total or total>MAX_SAMPLE_BYTES or not count or idx>=count or count!=(total+BLOCK-1)//BLOCK or len(data)!=min(BLOCK,total-idx*BLOCK):raise ValueError('chunk')
 return {'run_id':run,'packet_id':pid,'send_mono_ns':mono,'sample_id':sample,'chunk_index':idx,'chunk_count':count,'kind':kind,'total':total,'sha256':digest.hex()},data
def sender(a):
 out=a.path; manifest=[];pid=0;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
 samples=[(1,1,'rgb.jpg'),(2,2,'lidar_packets.bin'),(3,3,'capture_metadata.json')]
 with (out/'sender_packets.jsonl').open('x',encoding='utf-8') as f:
  for sample,kind,name in samples:
   path=out/name
   if not path.exists():continue
   data=path.read_bytes();sha=hashlib.sha256(data).digest();count=math.ceil(len(data)/BLOCK)
   manifest.append({'sample_id':sample,'kind':kind,'filename':name,'size':len(data),'sha256':sha.hex(),'chunks':count})
   for repeat in range(a.repeat):
    for idx in range(count):
     t=time.monotonic_ns();pkt=pack(a.run,pid,t,sample,kind,idx,count,len(data),sha,data[idx*BLOCK:(idx+1)*BLOCK]);sent=s.sendto(pkt,(a.host,a.port));m,_=unpack(pkt);m.update({'repeat':repeat,'wall_ns':time.time_ns(),'datagram_bytes':sent});f.write(json.dumps(m)+'\n');f.flush();pid+=1;time.sleep(1/a.pps)
 (out/'sender_manifest.json').write_text(json.dumps({'run_id':a.run,'samples':manifest,'packet_count':pid},indent=2),encoding='utf-8')
 print(json.dumps({'run_id':a.run,'packet_count':pid,'samples':manifest}),flush=True)
def receiver(a):
 out=a.path;out.mkdir(parents=True,exist_ok=False);s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(a.timeout);s.bind((a.host,a.port));print('RECEIVER_READY',flush=True)
 groups={};invalid=0;seen_ids={};dup_id=0;dup_chunk=0
 with (out/'receiver_packets.jsonl').open('x',encoding='utf-8') as f:
  while True:
   try:p,src=s.recvfrom(65535)
   except socket.timeout:break
   try:m,data=unpack(p)
   except ValueError:invalid+=1;continue
   if m['run_id']!=a.run:continue
   key=(m['sample_id'],m['kind'],m['total'],m['chunk_count'],m['sha256']);g=groups.setdefault(key,{})
   if m['packet_id'] in seen_ids:
    if seen_ids[m['packet_id']]!=p:raise ValueError('conflicting packet_id')
    dup_id+=1
   else:seen_ids[m['packet_id']]=p
   idx=m['chunk_index']
   if idx in g:
    if g[idx]!=data:raise ValueError('conflicting chunk data')
    dup_chunk+=1
   else:g[idx]=data
   m.update({'receiver_wall_ns':time.time_ns(),'receiver_monotonic_ns':time.monotonic_ns(),'source':src[0]});f.write(json.dumps(m)+'\n');f.flush()
 summary=[]
 for key,g in groups.items():
  sample,kind,total,count,sha=key;complete=len(g)==count;data=b''.join(g[i] for i in range(count)) if complete else b'';ok=complete and len(data)==total and hashlib.sha256(data).hexdigest()==sha
  if ok:(out/('sample_%d.bin'%sample)).write_bytes(data)
  summary.append({'sample_id':sample,'kind':kind,'total':total,'chunks_expected':count,'chunks_received':len(g),'complete_sha256_valid':ok,'sha256':sha,'missing_chunks':[i for i in range(count) if i not in g]})
 result={'run_id':a.run,'unique_packet_ids':len(seen_ids),'duplicate_packet_ids':dup_id,'duplicate_chunks':dup_chunk,'invalid_datagrams':invalid,'samples':summary}
 (out/'receiver_summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True)
def main():
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['send','receive']);p.add_argument('--path',type=pathlib.Path,required=True);p.add_argument('--host',required=True);p.add_argument('--run',type=int,required=True);p.add_argument('--port',type=int,default=39001);p.add_argument('--repeat',type=int,default=2);p.add_argument('--pps',type=float,default=10);p.add_argument('--timeout',type=float,default=30);a=p.parse_args();sender(a) if a.mode=='send' else receiver(a)
if __name__=='__main__':main()
