"""Offline synthetic tests; no hardware, keys or real network addresses."""
import json
import struct
import tempfile
import unittest
from pathlib import Path
from raw7 import *
from udp_probe_protocol import encode_packet,decode_packet

TA=bytes.fromhex('020000000001');AP=bytes.fromhex('020000000002');DEST=bytes.fromhex('020000000003')


def synthetic_frame(fc=0x0188,body=None):
    if body is None:
        app=encode_packet(17,37,123456)
        udp=struct.pack('!HHHH',40000,39001,8+len(app),0)+app
        ip=struct.pack('!BBHHHBBH4s4s',0x45,0,20+len(udp),1,0,64,17,0,bytes([192,0,2,1]),bytes([192,0,2,2]))
        words=struct.unpack('!10H',ip);s=sum(words)
        while s>>16:s=(s&65535)+(s>>16)
        ip=ip[:10]+struct.pack('!H',(~s)&65535)+ip[12:]
        body=bytes.fromhex('aaaa030000000800')+ip+udp
    header=struct.pack('<HH6s6s6sH',fc,0,AP,TA,DEST,0x1230)
    if fc&0x300==0x300:header+=DEST
    if fc&0x80:
        header+=b'\x00\x00'
        if fc&0x8000:header+=bytes(4)
    return header+body


def fixtures():
    raw=synthetic_frame()
    wire=[encode(ARMED,b'{}',serial=1),
          encode(RAW,raw,serial=2,timestamp=100,fc=0x0188,seq_ctrl=0x1230,ta=TA,ra=AP,flags=FCS_ABSENT|UPLINK),
          encode(CSI,bytes(range(114)),serial=3,timestamp=100,fc=0x0188,seq_ctrl=0x1230,ta=TA,ra=AP,source=TA,valid=1),
          encode(RAW,synthetic_frame(body=bytes.fromhex('aaaa03000000888e02010000')),serial=4,timestamp=101,fc=0x0188,seq_ctrl=0x1230,ta=TA,ra=AP,flags=FCS_ABSENT|EAPOL|UPLINK),
          encode(FINAL,b'{}',serial=5)]
    return b''.join(wire)


def decoded():
    d=Decoder();rows=d.feed(fixtures());assert not any(d.finish().get(k) for k in ('crc_error','incomplete_bytes','serial_discontinuity'))
    for i,r in enumerate(rows):r.update(host_time_ns=1700000000000000000+i*1000000,host_mono_ns=i*1000000)
    return rows


class RawTests(unittest.TestCase):
    def test_chunked_wire_and_bytes(self):
        d=Decoder();out=[];wire=fixtures()
        for b in wire:out+=d.feed(bytes([b]))
        self.assertEqual(len(out),5);self.assertEqual(bytes.fromhex(out[1]['raw_hex']),synthetic_frame())
        self.assertEqual(bytes.fromhex(out[2]['raw_hex']),bytes(range(114)));self.assertNotIn('serial_discontinuity',d.finish())

    def test_crc_resync(self):
        bad=bytearray(encode(STATS,b'{}',serial=1));bad[-1]^=1
        d=Decoder();rows=d.feed(bytes(bad)+encode(FINAL,b'{}',serial=2))
        self.assertEqual(len(rows),1);self.assertEqual(d.counts['crc_error'],1);self.assertGreater(d.counts['discarded_bytes'],0)

    def test_lengths_and_incomplete(self):
        with self.assertRaises(ValueError):encode(RAW,bytes(CAP+1))
        d=Decoder();data=encode(STATS,b'{}');d.feed(data[:-1]);self.assertGreater(d.finish()['incomplete_bytes'],0)
        for n in range(24):
            with self.assertRaises(ValueError):parse_header(bytes(n))
        d=Decoder();bad=bytearray(encode(STATS,b'{}'));struct.pack_into('<H',bad,36,5000)
        d.feed(bad+encode(FINAL,b'{}',serial=2));self.assertGreater(d.counts['bad_header'],0)

    def test_serial_gap_duplicate(self):
        d=Decoder();d.feed(encode(STATS,b'{}',serial=1)+encode(STATS,b'{}',serial=3)+encode(FINAL,b'{}',serial=3))
        self.assertEqual(d.counts['serial_discontinuity'],2)

    def test_qos_addr4_ht(self):
        h=parse_header(synthetic_frame(0x8388));self.assertEqual(h['header_len'],36)
        self.assertIsNotNone(h['address4']);self.assertEqual(h['qos_control'],0);self.assertEqual(h['ht_control'],'00000000')
        for n in (25,29,31,35):
            with self.assertRaises(ValueError):parse_header(synthetic_frame(0x8388)[:n])

    def test_udp_and_encrypted_reject(self):
        self.assertEqual(decode_packet(unencrypted_udp(synthetic_frame()))['packet_id'],37)
        self.assertIsNone(unencrypted_udp(synthetic_frame(0x4188)))
        self.assertIsNone(unencrypted_udp(synthetic_frame(0x0588)))
        x=bytearray(synthetic_frame());x[24]|=0x80
        self.assertIsNone(unencrypted_udp(x))

    def test_join_multiplicity(self):
        rows=decoded();pairs=join(rows);self.assertEqual(len(pairs),1);self.assertTrue(pairs[0]['unique'])
        pairs=join(rows+[dict(rows[1],record_serial=6)])
        self.assertFalse(pairs[0]['unique']);self.assertEqual(len(pairs[0]['frame_serials']),2)

    def test_pcap_raw_preserved_and_truncated_skipped(self):
        rows=decoded()
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'test.pcap';index=write_pcap(rows+[dict(rows[1],truncated=True)],p)
            self.assertEqual(len(index),2)
            data=p.read_bytes();self.assertEqual(struct.unpack_from('<I',data,20)[0],127)
            length=struct.unpack_from('<I',data,24+8)[0]
            self.assertEqual(data[40+15:40+length],synthetic_frame())

    def test_packet_id_association_retains_multiple_csi(self):
        from associate_ids import associate
        rows=decoded();rows.append(dict(rows[2],record_serial=6))
        extracted={'valid_ids':[dict(run_id=17,packet_id=37,sender_mono_ns=123456,
                   raw_frame={'record_serial':2},reassembly_scope='synthetic unfragmented test')]}
        out=associate(extracted,rows)
        self.assertEqual(len(out),1);self.assertEqual(len(out[0]['candidate_csi']),2)
        self.assertEqual(out[0]['packet_id'],37)


if __name__=='__main__':unittest.main()
