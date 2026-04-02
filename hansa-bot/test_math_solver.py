import unittest

from math_solver import solve_math_challenge


class TestMathSolver(unittest.TestCase):
    def test_subtract_from_phrase(self):
        q = "If you subtract 5 from 25 cookies, what remains?"
        self.assertEqual(solve_math_challenge(q), 20)

    def test_plus_symbol(self):
        self.assertEqual(solve_math_challenge("What is 7 + 8?"), 15)

    def test_minus_word(self):
        self.assertEqual(solve_math_challenge("What is 11 minus 3"), 8)


if __name__ == "__main__":
    unittest.main()
