import hashlib
import pathlib
import socket
import tempfile
import types
import unittest
from unittest.mock import patch
import multimodal_udp as udp


class PacketTest(unittest.TestCase):
    def test_realistic_last_chunk_and_crc(self):
        data=b'x'*401;sha=hashlib.sha256(data).digest()
        packet=udp.pack(3,4,5,6,1,1,2,len(data),sha,data[400:])
        meta,chunk=udp.unpack(packet)
        self.assertEqual((meta['run_id'],meta['packet_id'],meta['chunk_index'],chunk),(3,4,1,b'x'))
        damaged=bytearray(packet);damaged[-5]^=1
        with self.assertRaisesRegex(ValueError,'crc'):udp.unpack(damaged)

    def test_reject_unbounded_declared_sample(self):
        total=udp.MAX_SAMPLE_BYTES+1;count=(total+udp.BLOCK-1)//udp.BLOCK
        packet=udp.pack(1,2,3,4,1,0,count,total,b'\0'*32,b'a'*udp.BLOCK)
        with self.assertRaisesRegex(ValueError,'chunk'):udp.unpack(packet)

    def test_receiver_rejects_conflicting_reused_packet_id(self):
        sha=hashlib.sha256(b'a').digest()
        p1=udp.pack(1,9,10,1,1,0,1,1,sha,b'a')
        p2=udp.pack(1,9,11,1,1,0,1,1,sha,b'a')
        class FakeSocket:
            def __init__(self): self.items=iter([p1,p2])
            def settimeout(self, value): pass
            def bind(self, address): pass
            def recvfrom(self, size): return next(self.items),('127.0.0.1',1234)
        with tempfile.TemporaryDirectory() as tmp, patch.object(udp.socket,'socket',return_value=FakeSocket()):
            args=types.SimpleNamespace(path=pathlib.Path(tmp)/'recv',timeout=1,host='127.0.0.1',port=39001,run=1)
            with self.assertRaisesRegex(ValueError,'conflicting packet_id'):udp.receiver(args)


if __name__=='__main__':unittest.main()
