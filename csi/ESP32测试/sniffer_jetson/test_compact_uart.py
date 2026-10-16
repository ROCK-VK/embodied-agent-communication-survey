"""Offline transport checks; contains only synthetic addresses and bytes."""
import json
import unittest
from compact_uart import decode_record


class CompactTests(unittest.TestCase):
    def sample(self):
        return dict(e='C', i=1, t=123, fc=0x4188, q=32,
                    ta='02:00:00:00:00:01', ra='02:00:00:00:00:02',
                    f=2, ch=2, s=0, r=-44, st=0, rate=11, pr=1,
                    src='02:00:00:00:00:01', v=1, w=0, n=114, c=114,
                    g1=0, g2=0, x=1, hx=bytes(range(114)).hex())

    def test_bytes_and_fc(self):
        r=decode_record(json.dumps(self.sample()))
        self.assertEqual(bytes.fromhex(r['data_hex']),bytes(range(114)))
        self.assertEqual([r[k] for k in ('frame_type','subtype','to_ds','from_ds','protected')],[2,8,1,0,1])

    def test_frame_csi_join(self):
        a=self.sample();b=dict(a,e='F',i=2)
        x,y=[decode_record(json.dumps(r)) for r in (a,b)]
        self.assertEqual(tuple(x[k] for k in ('timestamp','ta','fc','seq_ctrl')),tuple(y[k] for k in ('timestamp','ta','fc','seq_ctrl')))

    def test_corruption_rejected(self):
        a=self.sample();a['hx']='00'
        with self.assertRaises(ValueError): decode_record(json.dumps(a))

    def test_control_pass_through(self):
        self.assertEqual(decode_record('{"event":"FINAL"}'),{'event':'FINAL'})


if __name__=='__main__': unittest.main()
