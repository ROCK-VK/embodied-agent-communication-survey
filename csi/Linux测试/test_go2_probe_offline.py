import threading
import types
import unittest
from go2_state_readonly_probe import make_callback


class ProbeTest(unittest.TestCase):
    def test_records_success_and_callback_failure_separately(self):
        counts={'topic':{'callbacks':0,'parsed':0,'callback_errors':0}}
        rows=[];cb=make_callback('topic',counts,rows,threading.Lock())
        good=types.SimpleNamespace(stamp=types.SimpleNamespace(sec=123,nanosec=456),position=[1,2,3],velocity=[0,0,0],mode=1)
        bad=types.SimpleNamespace(stamp=types.SimpleNamespace(sec='bad',nanosec=0))
        cb(good);cb(bad)
        self.assertEqual(counts['topic'],{'callbacks':2,'parsed':1,'callback_errors':1})
        self.assertEqual(rows[0]['stamp'],{'sec':123,'nanosec':456,'domain':'unknown'})
        self.assertEqual(rows[1]['error_type'],'ValueError')


if __name__=='__main__': unittest.main()
