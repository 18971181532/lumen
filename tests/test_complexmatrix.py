import unittest

from lumen.complexmatrix import (determinant, identity, lu_solve, matvec,
                                 residual, SingularMatrixError)


class ComplexMatrixTests(unittest.TestCase):
    def test_solve_complex_system(self):
        a = [[2 + 1j, 1 - 2j, 0], [1 + 0j, 3 - 2j, 1j],
             [0, 1 + 1j, 4]]
        x = [1 + 2j, -1 + 0.5j, 0.25]
        b = matvec(a, x)
        got = lu_solve(a, b)
        self.assertLess(residual(a, got, b), 1e-11)
        for want, actual in zip(x, got):
            self.assertAlmostEqual(abs(want - actual), 0.0, places=10)

    def test_real_entries_and_pivoting(self):
        a = [[0.0, 2.0], [3.0, 1.0]]
        b = [4.0, 7.0]
        got = lu_solve(a, b)
        self.assertAlmostEqual(got[0], 10.0 / 6.0, places=12)
        self.assertAlmostEqual(got[1], 2.0, places=12)

    def test_empty_system(self):
        self.assertEqual(lu_solve([], []), [])

    def test_identity_and_determinant(self):
        a = identity(3)
        self.assertEqual(lu_solve(a, [1 + 0j, 2j, 3]), [1 + 0j, 2j, 3])
        self.assertAlmostEqual(abs(determinant(a) - 1), 0, places=12)

    def test_singular_matrix(self):
        with self.assertRaises(SingularMatrixError):
            lu_solve([[1, 2], [2, 4]], [1, 2])


if __name__ == "__main__":
    unittest.main()
