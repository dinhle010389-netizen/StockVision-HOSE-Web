import numpy as np
import pytest

from app.risk import RiskMatrixError, analyze_hermitian_matrix, covariance_from_returns


def test_hermitian_matrix_spectrum_is_sorted_and_normalized():
    result = analyze_hermitian_matrix([[2.0, 1.0], [1.0, 2.0]])
    assert result["is_hermitian"]
    assert result["is_positive_semidefinite"]
    assert result["eigenvalues_desc"] == pytest.approx([3.0, 1.0])
    assert sum(result["variance_share_desc"]) == pytest.approx(1.0)


def test_complex_hermitian_matrix_accepted():
    result = analyze_hermitian_matrix([[2, 1j], [-1j, 2]])
    assert result["eigenvalues_desc"] == pytest.approx([3.0, 1.0])


def test_non_hermitian_rejected():
    with pytest.raises(RiskMatrixError, match="không Hermitian"):
        analyze_hermitian_matrix([[1, 2], [0, 1]])


def test_non_psd_covariance_rejected():
    with pytest.raises(RiskMatrixError, match="không nửa xác định dương"):
        analyze_hermitian_matrix([[1, 2], [2, 1]])


def test_covariance_from_returns():
    data = [[0.01, 0.02], [-0.02, -0.01], [0.03, 0.015], [-0.01, -0.02], [0.0, 0.005]]
    result = covariance_from_returns(data, ["FPT", "VCB"])
    assert result["symbols"] == ["FPT", "VCB"]
    assert result["observations"] == 5
    assert np.array(result["covariance"]).shape == (2, 2)
    assert result["risk_spectrum"]["is_hermitian"]


def test_returns_shape_and_nan_validation():
    with pytest.raises(RiskMatrixError):
        covariance_from_returns([[0.1], [0.2], [0.3]], ["FPT", "VCB"])
    with pytest.raises(RiskMatrixError):
        covariance_from_returns([[0.1], [float("nan")], [0.3]], ["FPT"])

def test_covariance_rejects_symbols_duplicate_after_case_and_whitespace_normalization():
    with pytest.raises(RiskMatrixError, match="duy nhất"):
        covariance_from_returns([[0.1, 0.2], [0.2, 0.1], [0.0, 0.3]], ["FPT", " fpt "])


def test_covariance_returns_canonical_uppercase_symbols():
    result = covariance_from_returns([[0.1], [0.2], [0.0]], [" fpt "])
    assert result["symbols"] == ["FPT"]
