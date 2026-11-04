"""Build a private sample/chunk/packet/CSI index from verified existing evidence.

No network access, decryption, clock conversion, or position interpolation.
Input CSI matches must already have been validated independently.
"""
import argparse
import collections
import hashlib
import json
import pathlib
import statistics
import struct


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def csi_receiver_times(path, selected):
    """Read RxSBasic v4 host systemTime, as used by the prior local parser."""
    result = {}
    with path.open('rb') as stream:
        index = 0
        while header := stream.read(4):
            if len(header) != 4:
                raise ValueError('truncated RxFrame length')
            size = struct.unpack('<I', header)[0]
            if size < 7 or size > 128 * 1024 * 1024:
                raise ValueError('invalid RxFrame length')
            frame = stream.read(size)
            if len(frame) != size:
                raise ValueError('truncated RxFrame')
            if index in selected:
                magic, version, count = struct.unpack_from('<IHB', frame)
                if magic != 0x20150315 or version not in (1, 2):
                    raise ValueError('unsupported RxFrame')
                offset = 7 if version == 1 else 9
                found = False
                for _ in range(count):
                    seglen = struct.unpack_from('<I', frame, offset)[0]
                    end = offset + 4 + seglen
                    if end > len(frame) or seglen < 3:
                        raise ValueError('bad segment length')
                    name_len = frame[offset + 4]
                    name = frame[offset + 5:offset + 5 + name_len].rstrip(b'\0')
                    segment_version = struct.unpack_from('<H', frame, offset + 5 + name_len)[0]
                    body = offset + 7 + name_len
                    if body > end:
                        raise ValueError('bad segment header')
                    if name == b'RxSBasic':
                        if found or segment_version != 4 or body + 18 > end:
                            raise ValueError('unsupported or duplicate RxSBasic')
                        result[index] = struct.unpack_from('<Q', frame, body + 10)[0]
                        found = True
                    offset = end
                if not found:
                    raise ValueError('missing RxSBasic')
            index += 1
    if result.keys() != selected:
        raise ValueError('CSI record index missing')
    return result


def time_stats(timestamps, widths=(0.1, 0.5, 1.0)):
    """Only full fixed windows between first and last observed CSI; no edge assumptions."""
    values = sorted(timestamps)
    if len(values) < 2:
        return {'count': len(values), 'reason': 'insufficient samples'}
    gaps = [(b-a)/1e9 for a,b in zip(values, values[1:])]
    def quantile(q):
        seq = sorted(gaps)
        x = (len(seq)-1)*q; lo = int(x); hi = min(lo+1,len(seq)-1)
        return seq[lo] + (seq[hi]-seq[lo])*(x-lo)
    start, end = values[0], values[-1]
    windows = {}
    for width in widths:
        ns = round(width*1e9); n = (end-start)//ns
        if n > 1000000:
            raise ValueError('excessive number of windows')
        occupied = {int((t-start)//ns) for t in values if t < start+n*ns}
        windows[str(width)] = {'full_windows': n, 'empty_windows': n-len(occupied)}
    return {'count':len(values), 'span_s':(end-start)/1e9, 'median_gap_s':statistics.median(gaps),
            'p95_gap_s':quantile(.95), 'max_gap_s':max(gaps), 'gaps_over_0_5s':sum(x>.5 for x in gaps),
            'gaps_over_1s':sum(x>1 for x in gaps), 'windows':windows,
            'scope':'between first and last matched CSI only; fixed nonoverlapping windows anchored at first match',
            'clock':'receiver RxSBasic systemTime; no cross-device clock subtraction'}


def build(root, source=None, rx=None, derived=None, csi_file=None):
    source = source or root/'capture-20261104-124200'
    rx = rx or root/'multimodal-20261104-g7PR7G'
    derived = derived or root/'offline_analysis_20261104'
    csi_file = csi_file or rx/'rx_6_261104_124504.csi'
    manifest = read_json(source/'sender_manifest.json')
    meta = read_json(source/'capture_metadata.json')
    verified = read_json(derived/'multimodal_verified_private.json')
    cross = read_json(derived/'crosscheck_private.json')
    sender = read_jsonl(source/'sender_packets.jsonl')
    receiver = read_jsonl(rx/'received/receiver_packets.jsonl')
    run = manifest['run_id']; samples = {x['sample_id']: x for x in manifest['samples']}
    if len(samples) != len(manifest['samples']): raise ValueError('duplicate sample')
    send = {}
    for row in sender:
        key = (row['run_id'],row['packet_id'])
        if key in send or row['run_id'] != run: raise ValueError('duplicate or wrong sender ID')
        sample = samples[row['sample_id']]
        if row['sha256'] != sample['sha256'] or row['total'] != sample['size'] or row['chunk_count'] != sample['chunks'] or not 0 <= row['chunk_index'] < sample['chunks']:
            raise ValueError('sender manifest mismatch')
        send[key] = row
    if len(send) != manifest['packet_count']: raise ValueError('sender count mismatch')
    rec = collections.defaultdict(list)
    for row in receiver:
        key = (row['run_id'], row['packet_id'])
        if key not in send: raise ValueError('receiver packet not in sender')
        for field in ('sample_id','chunk_index','chunk_count','total','sha256','kind','send_mono_ns'):
            if row[field] != send[key][field]: raise ValueError('receiver metadata mismatch')
        rec[key].append({k:row.get(k) for k in ('receiver_wall_ns','receiver_monotonic_ns')})
    matches = collections.defaultdict(list); refs = set()
    cross_lookup = collections.defaultdict(list)
    for row in cross: cross_lookup[(row['packet_id'],row['record'],row['csi_frame'])].append(row)
    if verified['run_id'] != run: raise ValueError('CSI run mismatch')
    for row in verified['rows']:
        key = (row['run_id'],row['packet_id']); ref=(row['record'],row['mpdu_index'])
        if key not in send or ref in refs or not row['csi_structural']: raise ValueError('bad CSI match')
        for field in ('sample_id','chunk_index','chunk_count','total','sha256','kind','send_mono_ns'):
            if row[field] != send[key][field]: raise ValueError('CSI metadata mismatch')
        checks=cross_lookup[(row['packet_id'],row['record'],row['pcap_frame'])]
        if len(checks)!=1 or len(checks[0]['matching_pcap_frames'])!=1:
            raise ValueError('missing unique PCAP crosscheck')
        refs.add(ref); matches[key].append({k:row[k] for k in ('record','mpdu_index','retry','pcap_frame')})
    if len(refs)!=verified['matched_records']: raise ValueError('verified count mismatch')
    times=csi_receiver_times(csi_file,{x[0] for x in refs})
    position_samples=meta.get('position_samples',[])
    positions={p['position_sample_id']:p for p in position_samples}
    if len(positions)!=len(position_samples): raise ValueError('duplicate position sample ID')
    associations=collections.defaultdict(list)
    for item in meta.get('position_associations',[]):
        if item['sample_id'] not in samples or item['position_sample_id'] not in positions:
            raise ValueError('unknown explicit position association')
        if not item.get('association_basis') or not item.get('association_evidence'):
            raise ValueError('position association requires explicit basis and evidence')
        associations[item['sample_id']].append(item)
    sample_rows=[]
    for sid, sample in samples.items():
        data=(source/sample['filename']).read_bytes()
        if len(data)!=sample['size'] or hashlib.sha256(data).hexdigest()!=sample['sha256']:
            raise ValueError('source sample digest mismatch')
        received_file=rx/'received'/('sample_%d.bin'%sid)
        if received_file.exists() and hashlib.sha256(received_file.read_bytes()).hexdigest()!=sample['sha256']:
            raise ValueError('receiver sample digest mismatch')
        chunks=[]
        for idx in range(sample['chunks']):
            packets=[]
            for key,row in send.items():
                if row['sample_id']!=sid or row['chunk_index']!=idx: continue
                csi=[{**x,'receiver_system_ns':times[x['record']]} for x in matches.get(key, [])]
                packets.append({'packet_id':row['packet_id'],'repeat':row.get('repeat'),
                                'send_monotonic_ns':row['send_mono_ns'],'send_wall_ns':row.get('wall_ns'),
                                'receiver_events':rec.get(key, []),'csi_records':csi})
            chunks.append({'chunk_index':idx,'packets':packets})
        sample_rows.append({'sample_id':sid,'filename':sample['filename'],'sha256':sample['sha256'],
                            'size':sample['size'],'position_associations':associations.get(sid,[]),'chunks':chunks})
    timing=time_stats([times[record] for record, _ in refs])
    ordered=[times[record] for record in sorted(times)]
    timing['receiver_clock_backsteps_in_record_order']=sum(b<a for a,b in zip(ordered,ordered[1:]))
    return {'schema_version':1,'run_id':run,'evidence':'existing locally verified decrypted MPDU and exact PCAP crosscheck; this index does not itself decrypt',
            'clocks':{'jetson_send':'monotonic_ns and wall_ns, sender boot identity not recorded',
                      'linux_csi':'RxSBasic v4 systemTime ns (receiver clock)',
                      'lidar':'raw type 0; MID360 protocol specifies unsynchronized sensor power-on clock; verify firmware',
                      'camera':'cached frame acquisition time and frameset unknown',
                      'position':'only explicit input associations; no cross-clock or nearest-neighbor inference'},
            'capture_metadata':meta,'samples':sample_rows,'timing':timing,
            'counts':{'sender_packets':len(send),'received_packet_ids':len(rec),'matched_packet_ids':len(matches),'matched_csi_records':len(refs)}}


def main():
    p=argparse.ArgumentParser();p.add_argument('--capture',required=True,type=pathlib.Path);p.add_argument('--output',required=True,type=pathlib.Path)
    p.add_argument('--source',type=pathlib.Path,help='directory containing sender manifest, metadata, samples and sender JSONL')
    p.add_argument('--receiver',type=pathlib.Path,help='directory containing received/ receiver logs and sample files')
    p.add_argument('--derived',type=pathlib.Path,help='directory containing verified CSI matches and crosscheck JSON')
    p.add_argument('--csi',type=pathlib.Path,help='original PicoScenes CSI file')
    a=p.parse_args()
    output=build(a.capture,a.source,a.receiver,a.derived,a.csi)
    with a.output.open('x',encoding='utf-8') as f: json.dump(output,f,ensure_ascii=False,indent=2)
    print(json.dumps({'counts':output['counts'],'timing':output['timing']},ensure_ascii=False))


if __name__=='__main__': main()
