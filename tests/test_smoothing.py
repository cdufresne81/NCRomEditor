"""
Tests for table smoothing logic.

Tests the compute_smoothed_values function which implements weighted
neighbor averaging for reducing jagged transitions in table data.
"""

import numpy as np
import pytest

from src.ui.table_viewer_helpers.operations import compute_smoothed_values

BLEND_FACTOR = 0.15


class TestSmoothing2D:
    """Test smoothing on 1D arrays (2D tables)."""

    def test_middle_cell_averages_neighbors(self):
        """A middle cell blends 15% toward the average of its two neighbors."""
        values = np.array([1.0, 5.0, 3.0])
        result = compute_smoothed_values(values, [(1, 0)], blend_factor=BLEND_FACTOR)

        # neighbors of index 1: [1.0, 3.0], avg = 2.0
        # smoothed = 5.0 + 0.15 * (2.0 - 5.0) = 5.0 - 0.45 = 4.55
        assert result[(1, 0)] == pytest.approx(4.55)

    def test_first_cell_uses_only_right_neighbor(self):
        """First cell has only one neighbor (right)."""
        values = np.array([10.0, 6.0, 8.0])
        result = compute_smoothed_values(values, [(0, 0)], blend_factor=BLEND_FACTOR)

        # neighbors of index 0: [6.0], avg = 6.0
        # smoothed = 10.0 + 0.15 * (6.0 - 10.0) = 10.0 - 0.6 = 9.4
        assert result[(0, 0)] == pytest.approx(9.4)

    def test_last_cell_uses_only_left_neighbor(self):
        """Last cell has only one neighbor (left)."""
        values = np.array([8.0, 6.0, 10.0])
        result = compute_smoothed_values(values, [(2, 0)], blend_factor=BLEND_FACTOR)

        # neighbors of index 2: [6.0], avg = 6.0
        # smoothed = 10.0 + 0.15 * (6.0 - 10.0) = 10.0 - 0.6 = 9.4
        assert result[(2, 0)] == pytest.approx(9.4)

    def test_smooth_already_linear_no_change(self):
        """Perfectly linear data should barely change (neighbors avg = self)."""
        values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = compute_smoothed_values(
            values, [(1, 0), (2, 0), (3, 0)], blend_factor=BLEND_FACTOR
        )

        # For index 2: neighbors [2.0, 4.0], avg = 3.0, smoothed = 3.0 (no change)
        assert result[(2, 0)] == pytest.approx(3.0)
        # For index 1: neighbors [1.0, 3.0], avg = 2.0, smoothed = 2.0 (no change)
        assert result[(1, 0)] == pytest.approx(2.0)

    def test_multiple_cells_calculated_from_original_values(self):
        """Smoothing uses original values, not already-smoothed ones (two-pass)."""
        values = np.array([1.0, 10.0, 1.0, 10.0, 1.0])
        result = compute_smoothed_values(
            values, [(1, 0), (2, 0), (3, 0)], blend_factor=BLEND_FACTOR
        )

        # Index 1: neighbors [1.0, 1.0], avg = 1.0
        # smoothed = 10.0 + 0.15 * (1.0 - 10.0) = 10.0 - 1.35 = 8.65
        assert result[(1, 0)] == pytest.approx(8.65)
        # Index 2: neighbors [10.0, 10.0], avg = 10.0
        # smoothed = 1.0 + 0.15 * (10.0 - 1.0) = 1.0 + 1.35 = 2.35
        assert result[(2, 0)] == pytest.approx(2.35)

    def test_single_element_array_no_neighbors(self):
        """Single-element array has no neighbors, nothing to smooth."""
        values = np.array([5.0])
        result = compute_smoothed_values(values, [(0, 0)], blend_factor=BLEND_FACTOR)
        assert result == {}


class TestSmoothing3D:
    """Test smoothing on 2D arrays (3D tables)."""

    def test_center_cell_uses_8_neighbors(self):
        """Center cell in a 3x3 grid averages all 8 surrounding cells."""
        values = np.array(
            [
                [1.0, 2.0, 3.0],
                [4.0, 5.0, 6.0],
                [7.0, 8.0, 9.0],
            ]
        )
        result = compute_smoothed_values(values, [(1, 1)], blend_factor=BLEND_FACTOR)

        # neighbors: [1,2,3,4,6,7,8,9], avg = 40/8 = 5.0
        # smoothed = 5.0 + 0.15 * (5.0 - 5.0) = 5.0
        assert result[(1, 1)] == pytest.approx(5.0)

    def test_corner_cell_uses_3_neighbors(self):
        """Corner cell (0,0) has only 3 neighbors."""
        values = np.array(
            [
                [10.0, 2.0],
                [4.0, 6.0],
            ]
        )
        result = compute_smoothed_values(values, [(0, 0)], blend_factor=BLEND_FACTOR)

        # neighbors: [2.0, 4.0, 6.0], avg = 4.0
        # smoothed = 10.0 + 0.15 * (4.0 - 10.0) = 10.0 - 0.9 = 9.1
        assert result[(0, 0)] == pytest.approx(9.1)

    def test_edge_cell_uses_5_neighbors(self):
        """Edge cell (0,1) in a 3x3 grid has 5 neighbors."""
        values = np.array(
            [
                [1.0, 2.0, 3.0],
                [4.0, 5.0, 6.0],
                [7.0, 8.0, 9.0],
            ]
        )
        result = compute_smoothed_values(values, [(0, 1)], blend_factor=BLEND_FACTOR)

        # neighbors of (0,1): [1.0, 3.0, 4.0, 5.0, 6.0], avg = 19/5 = 3.8
        # smoothed = 2.0 + 0.15 * (3.8 - 2.0) = 2.0 + 0.27 = 2.27
        assert result[(0, 1)] == pytest.approx(2.27)

    def test_uniform_grid_no_change(self):
        """Uniform grid should produce no change."""
        values = np.full((4, 4), 3.5)
        indices = [(r, c) for r in range(4) for c in range(4)]
        result = compute_smoothed_values(values, indices, blend_factor=BLEND_FACTOR)

        for key, val in result.items():
            assert val == pytest.approx(3.5)

    def test_spike_gets_reduced(self):
        """A single spike cell should be pulled toward its neighbors."""
        values = np.array(
            [
                [1.0, 1.0, 1.0],
                [1.0, 100.0, 1.0],
                [1.0, 1.0, 1.0],
            ]
        )
        result = compute_smoothed_values(values, [(1, 1)], blend_factor=BLEND_FACTOR)

        # neighbors all 1.0, avg = 1.0
        # smoothed = 100.0 + 0.15 * (1.0 - 100.0) = 100.0 - 14.85 = 85.15
        assert result[(1, 1)] == pytest.approx(85.15)


class TestSmoothingAutoRound:
    """Test that auto-round preserves format precision (the original bug)."""

    def test_auto_round_preserves_2_decimal_places(self):
        """With .2f format, smoothed values should keep 2 decimal places."""
        values = np.array(
            [
                [2.00, 2.03, 2.06],
                [2.00, 2.03, 2.06],
                [2.00, 2.03, 2.06],
            ]
        )
        result = compute_smoothed_values(
            values,
            [(1, 1)],
            blend_factor=BLEND_FACTOR,
            auto_round=True,
            precision=2,
        )

        # Value should stay at 2.03 (neighbors average to 2.03)
        assert result[(1, 1)] == pytest.approx(2.03)

    def test_auto_round_does_not_snap_to_tenths(self):
        """This is the exact bug that was reported - values should NOT snap to 0.1 increments."""
        values = np.array(
            [
                [1.97, 2.02, 2.04, 2.06, 2.07],
                [1.97, 2.02, 2.04, 2.06, 2.07],
                [1.97, 2.02, 2.04, 2.06, 2.07],
                [1.97, 2.02, 2.04, 2.06, 2.07],
                [1.97, 2.02, 2.04, 2.06, 2.07],
            ]
        )
        result = compute_smoothed_values(
            values,
            [(2, 2)],
            blend_factor=BLEND_FACTOR,
            auto_round=True,
            precision=2,
        )

        smoothed = result[(2, 2)]
        # Must NOT be rounded to 2.0 (the old bug)
        assert smoothed != 2.0, "Value was incorrectly snapped to 2.0"
        # Should stay close to original 2.04
        assert smoothed == pytest.approx(2.04, abs=0.02)

    def test_auto_round_0_decimal_places(self):
        """Integer format should round to whole numbers."""
        values = np.array([10.0, 15.0, 12.0])
        result = compute_smoothed_values(
            values,
            [(1, 0)],
            blend_factor=BLEND_FACTOR,
            auto_round=True,
            precision=0,
        )

        # neighbors [10.0, 12.0], avg = 11.0
        # smoothed = 15.0 + 0.15 * (11.0 - 15.0) = 15.0 - 0.6 = 14.4
        # rounded to 0 decimals = 14.0
        assert result[(1, 0)] == pytest.approx(14.0)

    def test_auto_round_3_decimal_places(self):
        """Higher precision format should preserve 3 decimal places."""
        values = np.array([1.000, 1.005, 1.010])
        result = compute_smoothed_values(
            values,
            [(1, 0)],
            blend_factor=BLEND_FACTOR,
            auto_round=True,
            precision=3,
        )

        # neighbors [1.000, 1.010], avg = 1.005
        # smoothed = 1.005 + 0.15 * (1.005 - 1.005) = 1.005
        assert result[(1, 0)] == pytest.approx(1.005)

    def test_no_auto_round_preserves_full_precision(self):
        """Without auto-round, values should have full float precision."""
        values = np.array([1.0, 5.0, 3.0])
        result = compute_smoothed_values(
            values, [(1, 0)], blend_factor=BLEND_FACTOR, auto_round=False
        )

        # 5.0 + 0.15 * (2.0 - 5.0) = 4.55
        assert result[(1, 0)] == 4.55  # Exact, not rounded


class TestSmoothingBlendFactor:
    """Test different blend factors."""

    def test_zero_blend_no_change(self):
        """Zero blend factor should leave values unchanged."""
        values = np.array([1.0, 10.0, 3.0])
        result = compute_smoothed_values(values, [(1, 0)], blend_factor=0.0)
        assert result[(1, 0)] == pytest.approx(10.0)

    def test_full_blend_replaces_with_average(self):
        """Blend factor of 1.0 should replace value with neighbor average."""
        values = np.array([2.0, 10.0, 6.0])
        result = compute_smoothed_values(values, [(1, 0)], blend_factor=1.0)

        # neighbors [2.0, 6.0], avg = 4.0
        # smoothed = 10.0 + 1.0 * (4.0 - 10.0) = 4.0
        assert result[(1, 0)] == pytest.approx(4.0)

    def test_repeated_smoothing_converges(self):
        """Applying smoothing multiple times should converge toward linearity."""
        values = np.array([0.0, 10.0, 0.0, 10.0, 0.0])

        for _ in range(50):
            result = compute_smoothed_values(
                values, [(1, 0), (2, 0), (3, 0)], blend_factor=BLEND_FACTOR
            )
            for (row, _col), val in result.items():
                values[row] = val

        # After many iterations, interior values should be close to each other
        assert np.std(values[1:4]) < 0.5


class TestSmoothingEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_selection(self):
        """Empty selection should return empty dict."""
        values = np.array([1.0, 2.0, 3.0])
        result = compute_smoothed_values(values, [], blend_factor=BLEND_FACTOR)
        assert result == {}

    def test_two_element_array(self):
        """Two-element array: each cell has exactly one neighbor."""
        values = np.array([0.0, 10.0])
        result = compute_smoothed_values(
            values, [(0, 0), (1, 0)], blend_factor=BLEND_FACTOR
        )

        # index 0: neighbor [10.0], smoothed = 0.0 + 0.15 * 10.0 = 1.5
        assert result[(0, 0)] == pytest.approx(1.5)
        # index 1: neighbor [0.0], smoothed = 10.0 + 0.15 * (0.0 - 10.0) = 8.5
        assert result[(1, 0)] == pytest.approx(8.5)

    def test_1x1_grid_no_neighbors(self):
        """1x1 2D grid has no neighbors."""
        values = np.array([[42.0]])
        result = compute_smoothed_values(values, [(0, 0)], blend_factor=BLEND_FACTOR)
        assert result == {}

    def test_large_values(self):
        """Smoothing should work with large values without overflow."""
        values = np.array([1e6, 2e6, 1e6])
        result = compute_smoothed_values(values, [(1, 0)], blend_factor=BLEND_FACTOR)

        # neighbors [1e6, 1e6], avg = 1e6
        # smoothed = 2e6 + 0.15 * (1e6 - 2e6) = 2e6 - 150000 = 1850000
        assert result[(1, 0)] == pytest.approx(1.85e6)

    def test_negative_values(self):
        """Smoothing should handle negative values correctly."""
        values = np.array([-10.0, 5.0, -10.0])
        result = compute_smoothed_values(values, [(1, 0)], blend_factor=BLEND_FACTOR)

        # neighbors [-10.0, -10.0], avg = -10.0
        # smoothed = 5.0 + 0.15 * (-10.0 - 5.0) = 5.0 - 2.25 = 2.75
        assert result[(1, 0)] == pytest.approx(2.75)

    def test_partial_selection_in_grid(self):
        """Only selected cells should appear in results."""
        values = np.array(
            [
                [1.0, 2.0, 3.0],
                [4.0, 5.0, 6.0],
                [7.0, 8.0, 9.0],
            ]
        )
        result = compute_smoothed_values(
            values, [(0, 0), (2, 2)], blend_factor=BLEND_FACTOR
        )

        assert len(result) == 2
        assert (0, 0) in result
        assert (2, 2) in result
        assert (1, 1) not in result
