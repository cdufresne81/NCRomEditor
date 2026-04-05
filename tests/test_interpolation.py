"""
Tests for interpolation logic and ScalingConverter integration.

These tests exercise actual production code: ScalingConverter round-trips
through interpolated values, _convert_expr_to_python expression conversion,
and the pure interpolation computation functions.
"""

import numpy as np
import pytest

from src.core.rom_reader import ScalingConverter, _convert_expr_to_python
from src.core.rom_definition import Scaling
from src.ui.table_viewer_helpers.interpolation import (
    compute_interpolated_1d_values,
    compute_interpolated_2d_values,
)


class TestConvertExprToPython:
    """Test the _convert_expr_to_python expression converter"""

    def test_caret_to_power(self):
        """x^2 should become x**2"""
        assert _convert_expr_to_python("x^2") == "x**2"

    def test_multiple_carets(self):
        """Multiple ^ should all be converted"""
        assert _convert_expr_to_python("x^2+y^3") == "x**2+y**3"

    def test_no_caret_unchanged(self):
        """Expressions without ^ should pass through unchanged"""
        assert _convert_expr_to_python("x*0.01-40") == "x*0.01-40"

    def test_already_python_power(self):
        """Expressions already using ** should not be double-converted"""
        result = _convert_expr_to_python("x**2")
        # re.sub replaces ^ with **, so ** stays as **
        assert result == "x**2"

    def test_complex_expression(self):
        """Complex expression with parentheses and caret"""
        assert _convert_expr_to_python("(x+1)^2*0.5") == "(x+1)**2*0.5"

    def test_empty_expression(self):
        """Empty string should return empty string"""
        assert _convert_expr_to_python("") == ""


class TestInterpolationWithScaling:
    """Test that interpolated values survive ScalingConverter round-trips.

    This catches issues where interpolation in display space produces values
    that don't convert cleanly back to raw space.
    """

    def _make_converter(self, toexpr="x*0.01", frexpr="x/0.01"):
        """Helper to create a ScalingConverter with given expressions"""
        scaling = Scaling(
            name="test",
            units="",
            toexpr=toexpr,
            frexpr=frexpr,
            format="%.2f",
            min=0,
            max=500,
            inc=0.01,
            storagetype="uint16",
            endian="big",
        )
        return ScalingConverter(scaling)

    def test_linear_interpolation_round_trip(self):
        """Linear interpolated values should survive display->raw->display"""
        converter = self._make_converter("x*0.1", "x/0.1")

        # Simulate: raw endpoints [100, 500], interpolate in display space
        raw_endpoints = np.array([100.0, 500.0])
        display_endpoints = converter.to_display(raw_endpoints)
        # display = [10.0, 50.0]

        # Interpolate 3 intermediate values in display space
        interpolated_display = np.linspace(
            display_endpoints[0], display_endpoints[1], 5
        )
        # [10, 20, 30, 40, 50]

        # Convert back to raw
        interpolated_raw = converter.from_display(interpolated_display)
        # [100, 200, 300, 400, 500]

        # Convert raw back to display to verify
        final_display = converter.to_display(interpolated_raw)
        np.testing.assert_array_almost_equal(
            interpolated_display, final_display, decimal=5
        )

    def test_offset_scaling_interpolation(self):
        """Interpolation with offset scaling (e.g., temperature)"""
        converter = self._make_converter("x*0.01-40", "(x+40)/0.01")

        # Raw endpoints in temp range
        raw_vals = np.array([4000.0, 16000.0])
        display_vals = converter.to_display(raw_vals)
        # display = [0.0, 120.0]

        # Interpolate
        interp = np.linspace(display_vals[0], display_vals[1], 5)
        raw_back = converter.from_display(interp)
        display_back = converter.to_display(raw_back)

        np.testing.assert_array_almost_equal(interp, display_back, decimal=3)

    def test_bilinear_interpolation_values_round_trip(self):
        """Bilinear-interpolated values should survive scaling round-trip"""
        converter = self._make_converter("x*0.5", "x/0.5")

        # 2x2 corner values in raw
        corners_raw = np.array([10.0, 20.0, 30.0, 40.0])
        corners_display = converter.to_display(corners_raw)

        # Bilinear interpolation at center
        f00, f10, f01, f11 = corners_display
        tx, ty = 0.5, 0.5
        center_display = (
            (1 - tx) * (1 - ty) * f00
            + tx * (1 - ty) * f10
            + (1 - tx) * ty * f01
            + tx * ty * f11
        )

        # Round-trip
        center_raw = converter.from_display(center_display)
        center_display_back = converter.to_display(center_raw)

        assert center_display_back == pytest.approx(center_display, rel=1e-5)

    def test_interpolation_near_zero(self):
        """Interpolation near zero shouldn't produce NaN or Inf"""
        converter = self._make_converter("x*0.001", "x/0.001")

        small_vals = np.array([0.0, 0.001, 0.002, 0.003])
        raw = converter.from_display(small_vals)
        display_back = converter.to_display(raw)

        assert not np.any(np.isnan(display_back))
        assert not np.any(np.isinf(display_back))
        np.testing.assert_array_almost_equal(small_vals, display_back, decimal=5)

    def test_negative_interpolation_values(self):
        """Negative values in display space should convert correctly"""
        converter = self._make_converter("x-128", "x+128")

        display_vals = np.array([-40.0, -20.0, 0.0, 20.0, 40.0])
        raw = converter.from_display(display_vals)
        display_back = converter.to_display(raw)

        np.testing.assert_array_almost_equal(display_vals, display_back, decimal=5)


class TestScalingConverterEdgeCases:
    """Test edge cases in ScalingConverter"""

    def test_identity_conversion(self):
        """Identity expression x should pass through unchanged"""
        scaling = Scaling(
            name="identity",
            units="",
            toexpr="x",
            frexpr="x",
            format="%.0f",
            min=0,
            max=255,
            inc=1,
            storagetype="uint8",
            endian="big",
        )
        converter = ScalingConverter(scaling)

        vals = np.array([0, 1, 127, 255], dtype=float)
        assert np.array_equal(converter.to_display(vals), vals)
        assert np.array_equal(converter.from_display(vals), vals)

    def test_large_array_conversion(self):
        """Conversion should handle arrays of typical ROM table size"""
        scaling = Scaling(
            name="test",
            units="",
            toexpr="x*0.01",
            frexpr="x/0.01",
            format="%.2f",
            min=0,
            max=500,
            inc=0.01,
            storagetype="uint16",
            endian="big",
        )
        converter = ScalingConverter(scaling)

        # Typical 20x20 3D table = 400 elements
        raw = np.arange(400, dtype=float) * 100
        display = converter.to_display(raw)
        raw_back = converter.from_display(display)

        np.testing.assert_array_almost_equal(raw, raw_back, decimal=3)

    def test_single_value_conversion(self):
        """Single scalar value (not array) should work"""
        scaling = Scaling(
            name="test",
            units="V",
            toexpr="x*0.001",
            frexpr="x/0.001",
            format="%.3f",
            min=0,
            max=5,
            inc=0.001,
            storagetype="uint16",
            endian="big",
        )
        converter = ScalingConverter(scaling)

        raw = 3500.0
        display = converter.to_display(raw)
        assert isinstance(display, float)
        assert display == pytest.approx(3.5)

        raw_back = converter.from_display(display)
        assert isinstance(raw_back, float)
        assert raw_back == pytest.approx(3500.0)


# ------------------------------------------------------------------
# Linear (1D) interpolation computation tests
# ------------------------------------------------------------------


class TestLinearInterpolation1D:
    """Test compute_interpolated_1d_values pure function."""

    def test_linear_3_points(self):
        """Midpoint between 1.0 and 3.0 should be 2.0."""
        result = compute_interpolated_1d_values(0, 1.0, 2, 3.0)
        assert result[1] == pytest.approx(2.0)

    def test_linear_5_points(self):
        """Endpoints 0.0 and 4.0 should produce evenly spaced intermediates."""
        result = compute_interpolated_1d_values(0, 0.0, 4, 4.0)
        assert result[1] == pytest.approx(1.0)
        assert result[2] == pytest.approx(2.0)
        assert result[3] == pytest.approx(3.0)

    def test_same_endpoints(self):
        """When both endpoints are equal, all intermediates should match."""
        result = compute_interpolated_1d_values(0, 5.0, 4, 5.0)
        for pos in [1, 2, 3]:
            assert result[pos] == pytest.approx(5.0)

    def test_2_adjacent_no_gap(self):
        """Only 2 adjacent cells (nothing between) returns empty."""
        result = compute_interpolated_1d_values(0, 1.0, 1, 3.0)
        assert result == {}

    def test_non_integer_values(self):
        """Interpolation with fractional endpoint values."""
        result = compute_interpolated_1d_values(0, 1.5, 2, 3.5)
        assert result[1] == pytest.approx(2.5)

    def test_negative_values(self):
        """Negative endpoint values interpolate correctly."""
        result = compute_interpolated_1d_values(0, -10.0, 4, 10.0)
        assert result[1] == pytest.approx(-5.0)
        assert result[2] == pytest.approx(0.0)
        assert result[3] == pytest.approx(5.0)

    def test_descending_values(self):
        """Interpolation works when last value is smaller than first."""
        result = compute_interpolated_1d_values(0, 10.0, 2, 4.0)
        assert result[1] == pytest.approx(7.0)


class TestLinearInterpolation1DAutoRound:
    """Regression tests: auto_round must use round(val, precision), not round_one_level_coarser."""

    def test_auto_round_preserves_2_decimal_places(self):
        """With precision=2, interpolated values should keep 2 decimal places."""
        # Endpoints chosen to produce a value with 2 meaningful decimals
        result = compute_interpolated_1d_values(
            0, 1.00, 4, 1.20, auto_round=True, precision=2
        )
        # Intermediate at pos 1: 1.00 + 0.25 * 0.20 = 1.05
        assert result[1] == pytest.approx(1.05)
        # Intermediate at pos 2: 1.00 + 0.50 * 0.20 = 1.10
        assert result[2] == pytest.approx(1.10)

    def test_auto_round_does_not_snap_to_tenths(self):
        """THE BUG REGRESSION: values like 2.04 must NOT snap to 2.0.

        round_one_level_coarser would detect 2 effective decimals in 2.04
        and round to 1 decimal → 2.0.  This test catches that regression.
        """
        # Endpoints that produce 2.04 at the midpoint
        result = compute_interpolated_1d_values(
            0, 2.00, 2, 2.08, auto_round=True, precision=2
        )
        midpoint = result[1]
        # Must be 2.04, NOT 2.0
        assert midpoint != 2.0, "Value was incorrectly snapped to 2.0"
        assert midpoint == pytest.approx(2.04)

    def test_auto_round_small_values_not_zeroed(self):
        """Small values like 0.01 must NOT be rounded to 0.0.

        round_one_level_coarser(0.01, '.2f') → effective=2 → round to 1 → 0.0.
        """
        result = compute_interpolated_1d_values(
            0, 0.00, 2, 0.02, auto_round=True, precision=2
        )
        midpoint = result[1]
        assert midpoint != 0.0, "Small value was incorrectly zeroed"
        assert midpoint == pytest.approx(0.01)

    def test_auto_round_0_decimal_places(self):
        """Integer format should round to whole numbers."""
        result = compute_interpolated_1d_values(
            0, 10.0, 2, 20.0, auto_round=True, precision=0
        )
        assert result[1] == pytest.approx(15.0)

    def test_auto_round_3_decimal_places(self):
        """Higher precision format preserves 3 decimals."""
        result = compute_interpolated_1d_values(
            0, 1.000, 3, 1.003, auto_round=True, precision=3
        )
        assert result[1] == pytest.approx(1.001)
        assert result[2] == pytest.approx(1.002)

    def test_no_auto_round_preserves_full_precision(self):
        """Without auto_round, full floating-point precision is kept."""
        result = compute_interpolated_1d_values(0, 0.0, 3, 1.0, auto_round=False)
        # 1/3 = 0.333...
        assert result[1] == pytest.approx(1 / 3)


# ------------------------------------------------------------------
# Bilinear (2D) interpolation computation tests
# ------------------------------------------------------------------


class TestBilinearInterpolation2D:
    """Test compute_interpolated_2d_values pure function."""

    def test_uniform_corners(self):
        """All corners same value → all cells get that value."""
        result = compute_interpolated_2d_values(5.0, 5.0, 5.0, 5.0, 3, 3)
        for (r, c), val in result.items():
            assert val == pytest.approx(5.0)

    def test_linear_gradient_horizontal(self):
        """TL=0, TR=10, BL=0, BR=10 → horizontal gradient."""
        result = compute_interpolated_2d_values(0.0, 10.0, 0.0, 10.0, 3, 3)
        # Column 0: all 0.0
        assert result[(0, 0)] == pytest.approx(0.0)
        assert result[(1, 0)] == pytest.approx(0.0)
        # Column 1 (middle): all 5.0
        assert result[(0, 1)] == pytest.approx(5.0)
        assert result[(1, 1)] == pytest.approx(5.0)
        # Column 2: all 10.0
        assert result[(0, 2)] == pytest.approx(10.0)

    def test_linear_gradient_vertical(self):
        """TL=0, TR=0, BL=10, BR=10 → vertical gradient."""
        result = compute_interpolated_2d_values(0.0, 0.0, 10.0, 10.0, 3, 3)
        # Row 0: all 0.0
        assert result[(0, 0)] == pytest.approx(0.0)
        assert result[(0, 1)] == pytest.approx(0.0)
        # Row 1 (middle): all 5.0
        assert result[(1, 0)] == pytest.approx(5.0)
        assert result[(1, 1)] == pytest.approx(5.0)
        # Row 2: all 10.0
        assert result[(2, 0)] == pytest.approx(10.0)

    def test_bilinear_center(self):
        """Center of 4 different corners = average of all four."""
        result = compute_interpolated_2d_values(1.0, 2.0, 3.0, 4.0, 3, 3)
        center = result[(1, 1)]
        assert center == pytest.approx(2.5)

    def test_corners_preserved(self):
        """Corner positions must get exact corner values."""
        v00, v10, v01, v11 = 1.0, 2.0, 3.0, 4.0
        result = compute_interpolated_2d_values(v00, v10, v01, v11, 3, 3)
        assert result[(0, 0)] == pytest.approx(v00)
        assert result[(0, 2)] == pytest.approx(v10)
        assert result[(2, 0)] == pytest.approx(v01)
        assert result[(2, 2)] == pytest.approx(v11)

    def test_single_row(self):
        """1-row grid: ty=0 everywhere, only horizontal interpolation."""
        result = compute_interpolated_2d_values(0.0, 10.0, 0.0, 10.0, 1, 3)
        assert result[(0, 0)] == pytest.approx(0.0)
        assert result[(0, 1)] == pytest.approx(5.0)
        assert result[(0, 2)] == pytest.approx(10.0)


class TestBilinearInterpolation2DAutoRound:
    """Regression tests: auto_round must use round(val, precision), not round_one_level_coarser."""

    def test_auto_round_preserves_2_decimal_places(self):
        """With precision=2, bilinear result keeps format precision."""
        result = compute_interpolated_2d_values(
            2.00, 2.10, 2.00, 2.10, 3, 3, auto_round=True, precision=2
        )
        center = result[(1, 1)]
        assert center == pytest.approx(2.05)

    def test_auto_round_does_not_snap_to_tenths(self):
        """THE BUG REGRESSION: VE-like values must not snap to 0.1 increments.

        round_one_level_coarser with '.2f' would take 2.04 → 2.0 (detects
        2 effective decimals, rounds to 1 decimal).
        """
        # Corners that produce ~2.04 at center
        result = compute_interpolated_2d_values(
            1.97, 2.07, 2.02, 2.06, 3, 3, auto_round=True, precision=2
        )
        center = result[(1, 1)]
        assert center != 2.0, "Value was incorrectly snapped to 2.0"
        # Expected: (1.97 + 2.07 + 2.02 + 2.06) / 4 = 2.03
        assert center == pytest.approx(2.03)

    def test_auto_round_small_values_not_zeroed(self):
        """Small values like 0.01 must NOT be zeroed."""
        result = compute_interpolated_2d_values(
            0.00, 0.02, 0.00, 0.02, 3, 3, auto_round=True, precision=2
        )
        center = result[(1, 1)]
        assert center != 0.0, "Small value was incorrectly zeroed"
        assert center == pytest.approx(0.01)

    def test_auto_round_0_decimal_places(self):
        """Integer format rounds to whole numbers."""
        result = compute_interpolated_2d_values(
            0.0, 100.0, 0.0, 100.0, 3, 3, auto_round=True, precision=0
        )
        center = result[(1, 1)]
        assert center == pytest.approx(50.0)

    def test_no_auto_round_preserves_full_precision(self):
        """Without auto_round, full floating-point precision is kept."""
        result = compute_interpolated_2d_values(0.0, 1.0, 1.0, 2.0, 3, 3)
        center = result[(1, 1)]
        # (0+1+1+2)/4 = 1.0
        assert center == pytest.approx(1.0)
