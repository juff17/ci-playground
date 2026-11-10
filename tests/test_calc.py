import unittest

from calc import add, divide, mean, median


class CalcTest(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

    def test_divide(self):
        self.assertEqual(divide(9, 3), 3)

    def test_divide_by_zero(self):
        with self.assertRaises(ZeroDivisionError):
            divide(1, 0)

    def test_mean(self):
        self.assertEqual(mean([1, 2, 3]), 2)

    def test_median(self):
        self.assertEqual(median([3, 1, 2]), 2)
        self.assertEqual(median([4, 1, 3, 2]), 2.5)
        with self.assertRaises(ValueError):
            median([])


if __name__ == "__main__":
    unittest.main()
