"""Bounded CS7R transport decoder, 802.11 metadata parser and radiotap PCAP writer.

No cryptography. Frame bytes stay unchanged. C5 dump_len excludes FCS.
"""
import collections
import json
import struct
import zlib

HEADER = struct.Struct('<4sBBHIIQHHBBbBHHHH6s6s6sHBB')
assert HEADER.size == 62
CAP = 4096
RAW, CSI, STATS, ARMED, FINAL = range(1, 6)
FCS_ABSENT, TRUNCATED, EAPOL, UPLINK = 1, 2, 4, 8
NAMES = {RAW:'FRAME', CSI:'CSI', STATS:'STATS', ARMED:'ARMED', FINAL:'FINAL'}


def mac(b): return ':'.join(f'{x:02x}' for x in b)


def encode(kind, payload=b'', *, serial=1, timestamp=0, mono_us=0, fc=0,
           seq_ctrl=0, channel=2, phy=2, rssi=-40, rx_state=0,
           flags=0, original=None, sig_len=0, ta=bytes(6), ra=bytes(6),
           source=bytes(6), rx_seq=0, valid=0, first_invalid=0):
    if kind not in NAMES or len(payload)>CAP: raise ValueError('kind/length')
    original=len(payload) if original is None else original
    h=HEADER.pack(b'CS7R',1,kind,62,serial,timestamp,mono_us,fc,seq_ctrl,channel,phy,
                  rssi,rx_state,flags,original,len(payload),sig_len,ta,ra,source,rx_seq,valid,first_invalid)
    data=h+payload
    return data+struct.pack('<I',zlib.crc32(data))


class Decoder:
    def __init__(self):
        self.buffer=bytearray();self.counts=collections.Counter();self.expected=1

    def feed(self, data):
        self.buffer.extend(data);out=[]
        while len(self.buffer)>=4:
            if self.buffer[:4]!=b'CS7R':
                self.counts['discarded_bytes']+=1;del self.buffer[0];continue
            if len(self.buffer)<62:break
            h=HEADER.unpack_from(self.buffer)
            magic,ver,kind,hlen,num,stamp,mono,fc,seq,ch,phy,rssi,state,flags,orig,n,sig,ta,ra,src,rxseq,valid,first=h
            if ver!=1 or kind not in NAMES or hlen!=62 or n>CAP or orig<n or (kind==CSI and n>2048):
                self.counts['bad_header']+=1;del self.buffer[0];continue
            total=62+n+4
            if len(self.buffer)<total:break
            block=bytes(self.buffer[:total])
            if zlib.crc32(block[:-4])!=struct.unpack_from('<I',block,total-4)[0]:
                self.counts['crc_error']+=1;del self.buffer[0];continue
            del self.buffer[:total]
            if num!=self.expected:self.counts['serial_discontinuity']+=1
            self.expected=num+1;self.counts[NAMES[kind]]+=1
            payload=block[62:-4]
            r=dict(event=NAMES[kind],record_serial=num,timestamp=stamp,esp_mono_us=mono,
                   fc=fc,seq_ctrl=seq,channel=ch,format=phy,rssi=rssi,rx_state=state,
                   flags=flags,original_len=orig,copied=n,sig_len=sig,ta=mac(ta),ra=mac(ra),
                   source=mac(src),rx_seq=rxseq,estimate_valid=valid,first_word_invalid=first)
            if kind in (RAW,CSI):
                r['raw_hex']=payload.hex();r['truncated']=bool(flags&TRUNCATED)
                if kind==RAW:
                    r['mac_header']=parse_header(payload)
                    if r['mac_header']['fc']!=fc or r['mac_header']['seq_ctrl']!=seq or r['mac_header']['ta']!=r['ta'] or r['mac_header']['ra']!=r['ra']:
                        r['raw_metadata_conflict']=True
                        self.counts['raw_metadata_conflict']+=1
            else:
                r['counters']=json.loads(payload)
            out.append(r)
        return out

    def finish(self):
        if self.buffer:self.counts['incomplete_bytes']=len(self.buffer)
        return dict(self.counts)


def parse_header(raw):
    if len(raw)<24:raise ValueError('short MAC header')
    fc,duration=struct.unpack_from('<HH',raw)
    if (fc>>2)&3!=2:raise ValueError('only Data MPDUs supported')
    tods,fromds=(fc>>8)&1,(fc>>9)&1
    seq=struct.unpack_from('<H',raw,22)[0];n=24
    out=dict(fc=fc,duration=duration,address1=mac(raw[4:10]),address2=mac(raw[10:16]),
             address3=mac(raw[16:22]),address4=None,ra=mac(raw[4:10]),ta=mac(raw[10:16]),
             seq_ctrl=seq,sequence=seq>>4,fragment=seq&15,to_ds=tods,from_ds=fromds,
             protected=(fc>>14)&1,retry=(fc>>11)&1,more_fragments=(fc>>10)&1,
             subtype=(fc>>4)&15,qos_control=None,ht_control=None,amsdu=False)
    if tods and fromds:
        if len(raw)<30:raise ValueError('short Address4')
        out['address4']=mac(raw[24:30]);n=30
    if out['subtype']&8:
        if len(raw)<n+2:raise ValueError('short QoS')
        out['qos_control']=struct.unpack_from('<H',raw,n)[0];out['amsdu']=bool(raw[n]&0x80);n+=2
        if fc&0x8000:
            if len(raw)<n+4:raise ValueError('short HT control')
            out['ht_control']=raw[n:n+4].hex();n+=4
    out['header_len']=n
    return out


def unencrypted_udp(raw):
    h=parse_header(raw)
    if h['protected'] or h['more_fragments'] or h['fragment'] or h['amsdu']:
        return None # Use Wireshark reassembly/decryption for these cases.
    body=raw[h['header_len']:]
    if len(body)<36 or body[:8]!=bytes.fromhex('aaaa030000000800'):return None
    ip=body[8:];ihl=(ip[0]&15)*4;total=int.from_bytes(ip[2:4],'big')
    if ip[0]>>4!=4 or ihl<20 or total<ihl+8 or total>len(ip) or ip[9]!=17:return None
    if int.from_bytes(ip[6:8],'big')&0x3fff:return None
    udp=ip[ihl:total];n=int.from_bytes(udp[4:6],'big')
    if n<8 or n!=len(udp):return None
    return udp[8:]


def match_key(r):return tuple(r[k] for k in ('timestamp','ta','fc','seq_ctrl'))


def join(rows):
    f,c=collections.defaultdict(list),collections.defaultdict(list)
    for r in rows:
        if r['event']=='FRAME':f[match_key(r)].append(r['record_serial'])
        if r['event']=='CSI':c[match_key(r)].append(r['record_serial'])
    # Preserve multiplicity; do not arbitrarily pick a match from an ambiguous key.
    return [dict(key=list(k),frame_serials=f[k],csi_serials=c[k],unique=len(f[k])==len(c[k])==1)
            for k in f.keys()&c.keys()]


def write_pcap(rows, path):
    """Radiotap linktype127, no FCS; absolute host receive time required.

    ESP timestamp stays in sidecar for joining; it is not a synchronized epoch clock.
    Truncated/error frames are rejected rather than silently treated as complete.
    """
    index=[]
    with path.open('xb') as f:
        f.write(struct.pack('<IHHIIII',0xa1b23c4d,2,4,0,0,8192,127))
        for r in rows:
            if r['event']!='FRAME':continue
            if r['truncated'] or r['original_len']!=r['copied'] or r['rx_state']!=0:continue
            if not r['flags']&FCS_ABSENT:raise ValueError('FCS semantics unknown')
            raw=bytes.fromhex(r['raw_hex']);ch=r['channel']
            freq=2484 if ch==14 else (2407+5*ch if 1<=ch<=13 else 5000+5*ch)
            rt=struct.pack('<BBHIBxHHb',0,0,15,0x2a,0,freq,0x80 if ch<=14 else 0x100,r['rssi'])
            ns=r['host_time_ns'];packet=rt+raw
            f.write(struct.pack('<IIII',ns//10**9,ns%10**9,len(packet),len(packet)));f.write(packet)
            index.append(dict(pcap_frame_number=len(index)+1,record_serial=r['record_serial'],
                              key=list(match_key(r)),mac_header=r['mac_header']))
    return index
