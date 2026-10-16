"""Synthetic EAPOL structural gate tests; no site credentials or crypto fixtures."""
import struct,unittest
from wpa2_gate8 import parse_eapol,handshake
from decrypt_probe8 import associate
from udp_probe_protocol import encode_packet

STA='02:00:00:00:00:01';AP='02:00:00:00:00:02'
def sample(message,replay=1):
    down=message in (1,3);ta=AP if down else STA;ra=STA if down else AP
    raw=bytearray(struct.pack('<HH',0x0208 if down else 0x0108,0))
    raw+=bytes.fromhex(ra.replace(':','')+ta.replace(':','')+AP.replace(':',''))+bytes(2)
    e=bytearray(99);e[0:5]=bytes([2,3,0,95,2])
    info={1:0x008a,2:0x010a,3:0x03ca,4:0x030a}[message];e[5:7]=info.to_bytes(2,'big');e[9:17]=replay.to_bytes(8,'big')
    if message!=4:e[17:49]=bytes([2 if message==2 else 1])*32
    if message!=1:e[81:97]=bytes([3])*16
    return raw+bytes.fromhex('aaaa03000000888e')+e

class GateTests(unittest.TestCase):
    def exchange(self):
        rows=[]
        for i in range(1,5):
            e=parse_eapol(sample(i,1 if i<=2 else 2),STA,AP);e['record_serial']=i;rows.append(e)
        return rows
    def test_complete(self):
        rows=self.exchange();self.assertEqual([r['message'] for r in rows],[1,2,3,4]);self.assertTrue(handshake(rows)['complete_four_way'])
    def test_four_rows_not_four_way(self):
        rows=self.exchange();self.assertFalse(handshake([rows[0]]*4)['complete_four_way'])
    def test_nonce_mismatch(self):
        rows=self.exchange();rows[2]['nonce']='ff'*32;self.assertFalse(handshake(rows)['complete_four_way'])
    def test_replay_mismatch(self):
        rows=self.exchange();rows[3]['replay_counter']=10;self.assertFalse(handshake(rows)['complete_four_way'])
    def test_truncated(self):
        with self.assertRaises(ValueError):parse_eapol(sample(2)[:-1],STA,AP)
    def test_group_or_request_not_pairwise_exchange(self):
        raw=sample(2);raw[24+8+5:24+8+7]=(0x0102).to_bytes(2,'big');self.assertIsNone(parse_eapol(raw,STA,AP)['message'])
    def test_wrong_pair(self):
        with self.assertRaises(ValueError):parse_eapol(sample(1),'02:00:00:00:00:03',AP)
    def association(self,fragment=0,corrupt=False,receiver=True):
        payload=bytearray(encode_packet(99,1,123))
        if corrupt:payload[-1]^=1
        fields=[['1','1','0x0800','4','39001',payload.hex(),'0x000001']]*2
        index=[dict(pcap_frame_number=1,event='CSI_DATA',record_serial=77,fragment=fragment,more_fragments=0,amsdu=False,
                    valid=1,rx_state=0,first_word_invalid=0,csi_len=114,csi_sha256='synthetic')]
        packet=dict(run_id=99,packet_id=1,sender_mono_ns=123)
        return associate(fields,index,[dict(event='SEND',**packet)],[dict(status='valid',**packet)] if receiver else [],99,39001)
    def test_atomic_multiplicity(self):
        r=self.association();self.assertTrue(r['minimum_poc_passed']);self.assertEqual(r['strict_observation_count'],2);self.assertEqual(r['strict_unique_packet_ids'],[1])
    def test_crc_is_required(self):
        r=self.association(corrupt=True);self.assertFalse(r['minimum_poc_passed']);self.assertEqual(r['invalid_csid_payloads'],2)
    def test_receiver_and_simple_ancestry_required(self):
        self.assertFalse(self.association(receiver=False)['minimum_poc_passed']);self.assertFalse(self.association(fragment=1)['minimum_poc_passed'])

if __name__=='__main__':unittest.main()
