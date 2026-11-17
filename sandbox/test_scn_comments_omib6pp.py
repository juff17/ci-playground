import unittest

from sandbox.scn_comments_omib6pp import spread


class SpreadTest(unittest.TestCase):
    def test_spread(self):
        self.assertEqual(spread([3, 9, 4]), 6)
