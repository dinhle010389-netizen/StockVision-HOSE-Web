"""Classical portfolio risk analytics using Hermitian/symmetric covariance matrices.

No Schrödinger dynamics or Born probabilities are used in the production path.
"""
from __future__ import annotations

from typing import Sequence
import numpy as np

from .normalizers import NormalizationError, normalize_symbol


class RiskMatrixError(ValueError):
    pass


def analyze_hermitian_matrix(matrix: Sequence[Sequence[complex]], *, tolerance: float = 1e-9) -> dict:
    arr = np.asarray(matrix, dtype=np.complex128)
    if arr.ndim != 2 or arr.shape[0] == 0 or arr.shape[0] != arr.shape[1]:
        raise RiskMatrixError("ma trận phải là ma trận vuông khác rỗng")
    if not np.isfinite(arr.real).all() or not np.isfinite(arr.imag).all():
        raise RiskMatrixError("ma trận có NaN hoặc vô cực")
    if not np.allclose(arr, arr.conj().T, atol=tolerance, rtol=tolerance):
        raise RiskMatrixError("ma trận không Hermitian: A phải bằng liên hợp chuyển vị của A")
    # Symmetrize away floating-point noise only after validating Hermitian structure.
    hermitian = (arr + arr.conj().T) / 2
    eigenvalues, eigenvectors = np.linalg.eigh(hermitian)
    eigenvalues = np.real(eigenvalues)
    scale = max(1.0, float(np.max(np.abs(eigenvalues))))
    if float(np.min(eigenvalues)) < -tolerance * scale:
        raise RiskMatrixError("ma trận không nửa xác định dương; không hợp lệ như ma trận hiệp phương sai")
    eigenvalues = np.clip(eigenvalues, 0.0, None)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]
    total = float(eigenvalues.sum())
    shares = (eigenvalues / total).tolist() if total > tolerance else [0.0] * len(eigenvalues)
    # First eigenvector is the dominant common-risk direction.
    principal_vector = eigenvectors[:, 0]
    vector_payload = [
        {"real": float(v.real), "imag": float(v.imag)} for v in principal_vector
    ]
    return {
        "dimension": int(arr.shape[0]),
        "is_hermitian": True,
        "is_positive_semidefinite": True,
        "eigenvalues_desc": [float(v) for v in eigenvalues],
        "variance_share_desc": [float(v) for v in shares],
        "principal_eigenvector": vector_payload,
        "trace": float(total),
        "minimum_eigenvalue": float(eigenvalues.min()),
    }


def covariance_from_returns(returns: Sequence[Sequence[float]], symbols: Sequence[str]) -> dict:
    arr = np.asarray(returns, dtype=np.float64)
    if arr.ndim != 2:
        raise RiskMatrixError("returns phải là ma trận [số phiên, số mã]")
    if arr.shape[1] != len(symbols):
        raise RiskMatrixError("số cột returns phải bằng số mã")
    if arr.shape[0] < 3:
        raise RiskMatrixError("cần ít nhất 3 phiên lợi suất để ước lượng hiệp phương sai")
    try:
        canonical_symbols = [normalize_symbol(s) for s in symbols]
    except (NormalizationError, TypeError) as exc:
        raise RiskMatrixError("danh sách mã chứa mã không hợp lệ") from exc
    if len(set(canonical_symbols)) != len(canonical_symbols):
        raise RiskMatrixError("danh sách mã phải duy nhất sau khi chuẩn hóa chữ hoa/khoảng trắng")
    if not np.isfinite(arr).all():
        raise RiskMatrixError("returns chứa NaN hoặc vô cực")
    cov = np.cov(arr, rowvar=False, ddof=1)
    cov = np.atleast_2d(cov)
    spectrum = analyze_hermitian_matrix(cov)
    return {
        "symbols": canonical_symbols,
        "observations": int(arr.shape[0]),
        "covariance": cov.tolist(),
        "risk_spectrum": spectrum,
        "interpretation": "Các vector riêng mô tả hướng biến động đồng thời; không phải tín hiệu mua/bán hoặc bảo đảm dự báo.",
    }
