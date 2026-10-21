"""Offline regression of actual control/benchmark parsers and EAPOL PCAP mapping."""
import unittest,struct,zlib,json,tempfile,sys,subprocess
from pathlib import Path
from staged_host import validate_ack,Session
from benchmark_host import Parser
from wire8c import encode,RAW,Decoder
from wpa2_gate8c import convert,parse_eapol
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sniffer_8_csi/tools'))
from test_wpa2_gate8 import sample,STA,AP

def bench(seq=1,n=64,kind=1):
 b=bytes((i*17+23)&255 for i in range(n));h=struct.pack('<4sBBHII',b'UB8C',1,kind,16,seq,n);return h+b+struct.pack('<I',zlib.crc32(h+b))

class ParserTests(unittest.TestCase):
 def test_benchmark_byte_chunks(self):
  p=Parser()
  for b in bench():p.feed(bytes([b]))
  self.assertEqual(p.c['received'],1);self.assertFalse(p.c['crc_error']);self.assertFalse(p.buf)
 def test_crc_and_gap(self):
  p=Parser();b=bytearray(bench());b[-1]^=1;p.feed(b+bench(2));self.assertEqual(p.c['crc_error'],1);self.assertEqual(p.c['serial_gap'],1)
 def test_duplicate_and_resync(self):
  p=Parser();p.feed(b'bad'+bench()+bench());self.assertEqual(p.c['duplicate'],1);self.assertEqual(p.c['resync'],3)
 def test_truncated_benchmark(self):
  p=Parser();p.feed(bench()[:-1]);self.assertTrue(p.buf);self.assertEqual(p.c['received'],0)
 def test_mode_ack_rejects_sent_only(self):
  with self.assertRaises(ValueError):validate_ack({'event':'CONTROL','counters':{'event':'MODE_SENT','mode':'PROBE_CAPTURE'}},'PROBE')
 def test_mode_ack_wrong_mode(self):
  with self.assertRaises(ValueError):validate_ack({'event':'CONTROL','counters':{'event':'MODE_ACK','mode':'HANDSHAKE_ONLY','counters_reset':False}},'PROBE')
 def test_coalesced_ack_and_final(self):
  ack=encode(7,json.dumps(dict(event='MODE_ACK',mode='STOP',counters_reset=False)).encode())
  final=encode(5,b'{}',serial=2)
  class Fake:
   in_waiting=len(ack+final)
   def read(self,n):self.in_waiting=0;return ack+final
  with tempfile.TemporaryDirectory() as td:
   s=Session(Fake(),Path(td));validate_ack(s.wait('MODE_ACK'),'STOP');self.assertEqual(s.wait('FINAL')['event'],'FINAL');s.close()
 def test_eapol_frame_name_not_silently_omitted(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);capture=base/'capture';capture.mkdir();wire=bytearray();times=[]
   for i in range(1,5):
    raw=sample(i,1 if i<=2 else 2);down=i in (1,3);ta=bytes.fromhex((AP if down else STA).replace(':',''));ra=bytes.fromhex((STA if down else AP).replace(':',''))
    wire+=encode(RAW,raw,serial=i,fc=0x0208 if down else 0x0108,seq_ctrl=0,ta=ta,ra=ra,flags=4|16)
    times.append(dict(record_serial=i,host_time_ns=1700000000000000000+i,host_mono_ns=i))
   (capture/'stream.bin').write_bytes(wire);(capture/'stream.bin.times.jsonl').write_text('\n'.join(map(json.dumps,times))+'\n',encoding='utf-8')
   r=convert(capture,base/'out',STA,AP);self.assertTrue(r['handshake']['complete_four_way']);self.assertEqual(r['handshake']['messages'],{'1':1,'2':1,'3':1,'4':1})
   index=json.loads((base/'out/frame_index_private.json').read_text(encoding='utf-8'));self.assertEqual(len(index),4);self.assertTrue(all(x['synthetic'] for x in index))
 def test_m4_requires_secure_key_info_bit(self):
  raw=sample(4);raw[37:39]=(0x010a).to_bytes(2,'big')
  self.assertIsNone(parse_eapol(bytes(raw),STA,AP)['message'])
 def test_non_eapol_data_frame_stays_in_pcap(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);capture=base/'capture';capture.mkdir()
   raw=bytes(sample(2)[:24])+bytes.fromhex('aaaa030000000800')+bytes(20)
   ta=bytes.fromhex(STA.replace(':',''));ra=bytes.fromhex(AP.replace(':',''))
   stream=encode(RAW,raw,serial=1,fc=0x0108,seq_ctrl=0,ta=ta,ra=ra,flags=4|16)
   (capture/'stream.bin').write_bytes(stream)
   (capture/'stream.bin.times.jsonl').write_text(json.dumps(dict(record_serial=1,host_time_ns=1700000000000000001,host_mono_ns=1))+'\n',encoding='utf-8')
   result=convert(capture,base/'out',STA,AP)
   index=json.loads((base/'out/frame_index_private.json').read_text(encoding='utf-8'))
   self.assertEqual(len(result['rejected_eapol']),1)
   self.assertEqual(len(index),1)
   self.assertGreater((base/'out/combined_private.pcap').stat().st_size,24+len(raw))
 def test_synthetic_cannot_be_real_decryption_evidence(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);(p/'handshake_private.json').write_text(json.dumps(dict(handshake=dict(complete_four_way=True))),encoding='utf-8');(p/'frame_index_private.json').write_text('[{"synthetic":true}]',encoding='utf-8')
   cmd=[sys.executable,str(Path(__file__).with_name('decrypt_probe8.py')),'--tshark','unused','--conversion',td,'--profile','unused','--sender-log','unused','--receiver-log','unused','--run-id','1','--output',str(p/'out')]
   r=subprocess.run(cmd,capture_output=True,text=True);self.assertNotEqual(r.returncode,0);self.assertIn('Synthetic engineering records',r.stderr)

if __name__=='__main__':unittest.main()
