"""Complex dense linear algebra: LU with partial pivoting.

The photonic circuit solver reduces to one complex linear system
``(I - S P) a = b`` per wavelength; this module solves it without numpy.
"""


class SingularMatrixError(ValueError):
    pass


def zeros(n, m=None):
    m = n if m is None else m
    return [[0j] * m for _ in range(n)]


def identity(n):
    out = zeros(n)
    for i in range(n):
        out[i][i] = 1.0 + 0j
    return out


def lu_solve(a, b):
    """Solve A x = b for real or complex entries."""
    n = len(b)
    if n == 0:
        return []
    m = [list(row) for row in a]
    x = list(b)
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-300:
            raise SingularMatrixError(
                "singular system at column %d (unconnected port or a "
                "zero-gain loop?)" % col)
        if piv != col:
            m[col], m[piv] = m[piv], m[col]
            x[col], x[piv] = x[piv], x[col]
        inv = 1.0 / m[col][col]
        for r in range(col + 1, n):
            factor = m[r][col] * inv
            if factor == 0:
                continue
            m[r][col] = 0j
            for c in range(col + 1, n):
                m[r][c] -= factor * m[col][c]
            x[r] -= factor * x[col]
    for r in range(n - 1, -1, -1):
        acc = x[r]
        for c in range(r + 1, n):
            acc -= m[r][c] * x[c]
        x[r] = acc / m[r][r]
    return x


def matvec(a, x):
    return [sum(row[j] * x[j] for j in range(len(x))) for row in a]


def residual(a, x, b):
    return max((abs(v) for v in
                (matvec(a, x)[i] - b[i] for i in range(len(b)))), default=0.0)


def determinant(a):
    n = len(a)
    m = [list(row) for row in a]
    sign = 1.0
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-300:
            return 0j
        if piv != col:
            m[col], m[piv] = m[piv], m[col]
            sign = -sign
        inv = 1.0 / m[col][col]
        for r in range(col + 1, n):
            factor = m[r][col] * inv
            for c in range(col + 1, n):
                m[r][c] -= factor * m[col][c]
    det = complex(sign)
    for i in range(n):
        det *= m[i][i]
    return det
