import hashlib
import json
import pathlib
import struct
import tempfile
import unittest

import multimodal_offline_index as index


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding='utf-8')


def frame(ns):
    name=b'RxSBasic\0'; body=bytes(10)+struct.pack('<Q',ns)+bytes(22)
    segment=bytes([len(name)])+name+struct.pack('<H',4)+body
    inner=struct.pack('<IHB',0x20150315,1,1)+struct.pack('<I',len(segment))+segment
    return struct.pack('<I',len(inner))+inner


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=pathlib.Path(self.temp.name)
        source=self.root/'capture-20261104-124200'; dest=self.root/'multimodal-20261104-g7PR7G'; derived=self.root/'offline_analysis_20261104'
        source.mkdir(); (dest/'received').mkdir(parents=True); derived.mkdir()
        data=b'abc'; sha=hashlib.sha256(data).hexdigest(); (source/'rgb.jpg').write_bytes(data)
        (dest/'received/sample_1.bin').write_bytes(data)
        dump(source/'sender_manifest.json',{'run_id':7,'packet_count':2,'samples':[{'sample_id':1,'filename':'rgb.jpg','sha256':sha,'size':3,'chunks':1}]})
        dump(source/'capture_metadata.json',{'position':{'available':False}})
        base={'run_id':7,'sample_id':1,'chunk_index':0,'chunk_count':1,'kind':1,'total':3,'sha256':sha,'send_mono_ns':10}
        rows=[{**base,'packet_id':i,'repeat':i} for i in range(2)]
        (source/'sender_packets.jsonl').write_text('\n'.join(map(json.dumps,rows)),encoding='utf-8')
        (dest/'received/receiver_packets.jsonl').write_text(json.dumps(rows[0])+'\n',encoding='utf-8')
        matches=[{**base,'packet_id':0,'record':i,'mpdu_index':0,'retry':bool(i),'pcap_frame':i+4,'csi_structural':True} for i in range(2)]
        dump(derived/'multimodal_verified_private.json',{'run_id':7,'matched_records':2,'rows':matches})
        dump(derived/'crosscheck_private.json',[{'packet_id':0,'record':i,'csi_frame':i+4,'matching_pcap_frames':[10+i]} for i in range(2)])
        (dest/'rx_6_261104_124504.csi').write_bytes(frame(1_000_000_000)+frame(1_300_000_000))

    def tearDown(self): self.temp.cleanup()

    def test_one_to_many_and_missing_packet(self):
        out=index.build(self.root)
        self.assertEqual(out['counts'],{'sender_packets':2,'received_packet_ids':1,'matched_packet_ids':1,'matched_csi_records':2})
        first,second=out['samples'][0]['chunks'][0]['packets']
        self.assertEqual(len(first['csi_records']),2)
        self.assertEqual(second['csi_records'],[])
        self.assertFalse(out['capture_metadata']['position']['available'])
        self.assertAlmostEqual(out['timing']['max_gap_s'],.3)
        self.assertEqual(out['timing']['windows']['0.1']['empty_windows'],2)

    def test_reject_bad_sample_digest(self):
        (self.root/'capture-20261104-124200/rgb.jpg').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'digest'): index.build(self.root)

    def test_reject_ambiguous_crosscheck(self):
        p=self.root/'offline_analysis_20261104/crosscheck_private.json'; rows=index.read_json(p)
        rows[0]['matching_pcap_frames']=[3,4];dump(p,rows)
        with self.assertRaisesRegex(ValueError,'crosscheck'): index.build(self.root)

    def test_edge_windows_do_not_claim_full_coverage(self):
        result=index.time_stats([0,250_000_000])
        self.assertEqual(result['windows']['0.1'],{'full_windows':2,'empty_windows':1})
        self.assertEqual(result['windows']['1.0']['full_windows'],0)

    def test_explicit_position_association_requires_evidence(self):
        meta=self.root/'capture-20261104-124200/capture_metadata.json'
        position={'position_sample_id':'p1','xyz':[1,2,3],'stamp':{'value':12,'domain':'unknown'}}
        association={'sample_id':1,'position_sample_id':'p1','association_basis':'hardware_trigger'}
        dump(meta,{'position_samples':[position],'position_associations':[association]})
        with self.assertRaisesRegex(ValueError,'basis and evidence'): index.build(self.root)
        association['association_evidence']='trigger_counter=4'
        dump(meta,{'position_samples':[position],'position_associations':[association]})
        out=index.build(self.root)
        self.assertEqual(out['samples'][0]['position_associations'],[association])


if __name__=='__main__': unittest.main()
