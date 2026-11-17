import unittest

from sandbox.scn_comments_omjsmxu import spread


class SpreadTest(unittest.TestCase):
    def test_spread(self):
        self.assertEqual(spread([3, 9, 4]), 6)

    def test_empty_list_raises(self):
        with self.assertRaisesRegex(ValueError, "at least one value"):
            spread([])
