import importlib.util
import json
from pathlib import Path
import sys
import time
import unittest
import numpy as np
from runtime import Playback, phase, select_states


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.meta={'scale':[1]*6,'codebook':[[0]*6,[1]*6,[-1]*6], 'transition_weight':.1,'lookahead_frames':2,'coverage_threshold':1}
    def test_pingpong_has_no_skipped_boundary(self):
        self.assertEqual([phase(i,4) for i in range(13)],[0,1,2,3,2,1,0,1,2,3,2,1,0])
    def test_exact_known_state(self):
        states,_=select_states(np.ones((20,6)),self.meta)
        np.testing.assert_equal(states,np.ones(20,int))
    def test_silence_hard_override(self):
        c=np.ones((10,6));c[3:5]=0
        states,_=select_states(c,self.meta)
        self.assertEqual(states[3:5].tolist(),[0,0])
    def test_no_future_changes_committed_decisions(self):
        x=np.ones((15,6));a,_=select_states(x,self.meta);x[10:]=-1;b,_=select_states(x,self.meta)
        np.testing.assert_equal(a[:8],b[:8])
    def test_unknown_controls_are_flagged(self):
        _,m=select_states(np.full((10,6),100),self.meta)
        self.assertEqual(m['outside_coverage_fraction'],1)
    def test_reject_nonfinite(self):
        with self.assertRaises(ValueError):select_states(np.full((2,6),np.nan),self.meta)
    def test_cancel_fences_late_and_queued_frames(self):
        p=Playback();old=p.begin([1]*100);self.assertEqual(p.state_at(5,old),1)
        t=time.perf_counter();p.interrupt();elapsed=time.perf_counter()-t
        self.assertLess(elapsed,.04);self.assertEqual(p.state_at(5,old),0)
        new=p.begin([2]*100);self.assertEqual(p.state_at(0,old),0);self.assertEqual(p.state_at(0,new),2)
        self.assertEqual(p.state_at(100,new),0)
    def test_empty_timeline(self):
        states,m=select_states(np.empty((0,6)),self.meta);self.assertEqual(len(states),0)
    def test_visual_runtime_does_not_import_image_inference(self):
        self.assertNotIn('torch',sys.modules);self.assertNotIn('cv2',sys.modules)


if __name__=='__main__':unittest.main()
