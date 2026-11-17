import unittest

from sandbox.scn_failing_omjs3rp import last_n


class LastNTest(unittest.TestCase):
    def test_last_n(self):
        self.assertEqual(last_n([1, 2, 3, 4], 2), [3, 4])
        self.assertEqual(last_n(["a", "b"], 1), ["b"])
