"""Offline atomic segmentation and integrity checks; only synthetic bytes."""
import struct,unittest,tempfile,json,subprocess,os
from pathlib import Path
from wire8c import encode,Decoder,ATOMIC,parse_header,assemble_api_parts


def sample(**overrides):
    ta=bytes.fromhex('020000000001');ra=bytes.fromhex('020000000002')
    hdr=struct.pack('<HH6s6s6sHH',0x4188,0,ra,ta,ra,16,0)
    body=bytes.fromhex('0100002000000000')+bytes(range(30))+bytes(8);csi=bytes(range(114));meta=bytes(48)
    prefix=struct.pack('<8Hi',26,len(body),len(body),114,114,48,80,76,26)
    args=dict(serial=1,timestamp=123,fc=0x4188,seq_ctrl=16,ta=ta,ra=ra,source=ta,valid=1)
    args.update(overrides);return encode(ATOMIC,prefix+meta+hdr+body+csi,**args)


class AtomicTests(unittest.TestCase):
    def test_segment_bytes_and_binding(self):
        d=Decoder();rows=[]
        for b in sample():rows+=d.feed(bytes([b]))
        r=rows[0];self.assertEqual(r['event'],'CSI_DATA');self.assertTrue(r['native_callback_binding'])
        self.assertEqual(r['csi_hex'],bytes(range(114)).hex());self.assertEqual(r['hdr_len'],26)
        self.assertEqual(r['payload_len'],46);self.assertEqual(r['payload_minus_hdr'],26)
        self.assertEqual(r['mac_header']['seq_ctrl'],16);self.assertFalse(d.finish().get('raw_metadata_conflict'))

    def test_crc_and_sequence(self):
        d=Decoder();b=bytearray(sample());b[-1]^=1;d.feed(b+sample(serial=2))
        self.assertEqual(d.counts['crc_error'],1);self.assertEqual(d.counts['serial_discontinuity'],1)

    def test_incomplete_and_cap(self):
        d=Decoder();d.feed(sample()[:-1]);self.assertGreater(d.finish()['incomplete_bytes'],0)
        with self.assertRaises(ValueError):encode(ATOMIC,bytes(4097))

    def test_metadata_conflict_not_repaired(self):
        d=Decoder();r=d.feed(sample(seq_ctrl=32))[0]
        self.assertTrue(r['raw_metadata_conflict']);self.assertEqual(r['mac_header']['seq_ctrl'],16)

    def test_candidate_pcap_with_standard_parser(self):
        tool=os.environ.get('CSI_TEST_TSHARK')
        if not tool:self.skipTest('set CSI_TEST_TSHARK for offline integration')
        r=Decoder().feed(sample())[0]
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'test.pcap';raw=bytes.fromhex(r['hdr_hex']+r['payload_hex'])
            rt=struct.pack('<BBHIBxHHb',0,0,15,0x2a,0,2417,0x80,-40);packet=rt+raw
            p.write_bytes(struct.pack('<IHHIIII',0xa1b23c4d,2,4,0,0,8192,127)+struct.pack('<IIII',1700000000,0,len(packet),len(packet))+packet)
            out=subprocess.run([tool,'-n','-r',str(p),'-o','wlan.enable_decryption:FALSE','-T','fields','-e','wlan.ccmp.extiv'],capture_output=True,text=True,check=True)
            self.assertIn('0001',out.stdout)

    def test_api_pointer_overlap_not_guessed(self):
        r=Decoder().feed(sample())[0];expected=bytes.fromhex(r['hdr_hex']+r['payload_hex'])
        r['payload_hex']=r['hdr_hex'][-4:]+r['payload_hex'];r['payload_minus_hdr']=24
        r['payload_len']+=2;r['payload_copied']+=2
        self.assertEqual(assemble_api_parts(r),expected)
        r['payload_hex']='ffff'+r['payload_hex'][4:]
        with self.assertRaises(ValueError):assemble_api_parts(r)


if __name__=='__main__':unittest.main()
