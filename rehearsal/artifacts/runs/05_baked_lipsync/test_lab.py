import json
import unittest
from unittest.mock import patch

import numpy as np
from lab import Driver, Handler, HERE, PRIVATE, synthesize


class SafetyTests(unittest.TestCase):
    def test_invalid_text_never_starts_process(self):
        with patch('lab.subprocess.run') as run:
            for text in ('', ' ', 'a'*501, None, 17):
                with self.assertRaises(ValueError):
                    synthesize(text)
            run.assert_not_called()

    def test_path_traversal(self):
        h = object.__new__(Handler)
        for path in ('/data/../../../.env', '/data/%2e%2e/%2e%2e/.env', '/../lab.py'):
            self.assertEqual(h.translate_path(path), str(HERE/'__not_found__'))
        self.assertEqual(h.translate_path('/data/model/config.json'),str(PRIVATE/'model/config.json'))


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = Driver()

    def test_real_cpu_model_shape_and_finiteness(self):
        bs, ms = self.driver.infer(np.zeros(16000, np.float32))
        self.assertEqual(self.driver.session.get_providers(), ['CPUExecutionProvider'])
        self.assertEqual(bs.shape, (30,52))
        self.assertGreater(ms, 0)
        self.assertTrue(np.isfinite(bs).all())

    def test_silence_gate_closes_both_variants(self):
        pcm = np.zeros(16000, np.float32)
        bs, _ = self.driver.infer(pcm)
        for curve in self.driver.curves(pcm, bs):
            np.testing.assert_allclose(curve, np.tile([0,.3,.2], (30,1)))

    def test_heldout_calibration_and_shared_timebase(self):
        calibration = json.loads((PRIVATE/'calibration.json').read_text())
        for name in ('closures','rounding','training'):
            entry = json.loads((PRIVATE/f'{name}.json').read_text())
            self.assertNotEqual(entry['text'],calibration['phrase'])
            self.assertEqual(len(entry['model']),len(entry['energy']))
            self.assertAlmostEqual(len(entry['model'])/entry['fps'],entry['duration_s'])
            self.assertTrue(np.isfinite(entry['model']).all())


if __name__ == '__main__':
    unittest.main(verbosity=2)
