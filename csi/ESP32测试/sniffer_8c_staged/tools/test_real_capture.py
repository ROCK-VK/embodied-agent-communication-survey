"""No serial/network operations; validate real-capture transition gates."""
import unittest
from capture_real8c import probe_allowed
class RealGateTests(unittest.TestCase):
 def good(self):return dict(min_free_heap=108116,queue_drop=0)
 def test_complete(self):self.assertTrue(probe_allowed(dict(complete_four_way=True),self.good()))
 def test_incomplete(self):self.assertFalse(probe_allowed(dict(complete_four_way=False),self.good()))
 def test_drop(self):c=self.good();c['queue_drop']=1;self.assertFalse(probe_allowed(dict(complete_four_way=True),c))
 def test_heap(self):c=self.good();c['min_free_heap']=12;self.assertFalse(probe_allowed(dict(complete_four_way=True),c))
 def test_truncated(self):c=self.good();c['payload_truncated']=1;self.assertFalse(probe_allowed(dict(complete_four_way=True),c))
if __name__=='__main__':unittest.main()
