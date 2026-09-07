import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError

SOURCE=Path(__file__).resolve().parents[1]/'07_avatar_graph'
sys.path.insert(0,str(SOURCE))
from media_http import byte_range


class RangeTests(unittest.TestCase):
    def test_full(self):self.assertEqual(byte_range(None,100),(0,99,False))
    def test_first_bytes(self):self.assertEqual(byte_range('bytes=0-1',100),(0,1,True))
    def test_tail(self):self.assertEqual(byte_range('bytes=-20',100),(80,99,True))
    def test_open_end(self):self.assertEqual(byte_range('bytes=30-',100),(30,99,True))
    def test_clamp(self):self.assertEqual(byte_range('bytes=90-120',100),(90,99,True))
    def test_bad_ranges(self):
        for text in ['bytes=100-','bytes=9-2','bytes=-0','bytes=','bytes=0-1,4-5']:
            with self.subTest(text=text),self.assertRaises(ValueError):byte_range(text,100)


if __name__=='__main__':unittest.main()
