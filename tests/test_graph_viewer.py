"""
Tests for _GraphPlotMixin color calculation methods.

These are pure-computation methods that take numpy arrays and return
color arrays — no rendering or Qt widgets needed.
"""

import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from src.core.rom_definition import (
    RomDefinition,
    RomID,
    Scaling,
    Table,
    TableType,
)
from src.utils.colormap import ColorMap

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_romid():
    return RomID(
        xmlid="test",
        internalidaddress="0x0",
        internalidstring="T",
        ecuid="",
        make="",
        model="",
        flashmethod="",
        memmodel="",
        checksummodule="",
    )


def _make_scaling(name="TestScaling", min_val=0.0, max_val=100.0):
    return Scaling(
        name=name,
        units="",
        toexpr="x",
        frexpr="x",
        format="%0.2f",
        min=min_val,
        max=max_val,
        inc=1.0,
        storagetype="float",
        endian="big",
    )


def _make_definition(scalings=None):
    if scalings is None:
        scalings = {"TestScaling": _make_scaling()}
    return RomDefinition(romid=_make_romid(), scalings=scalings)


def _make_table(scaling="TestScaling"):
    return Table(
        name="Test",
        address="0x100",
        type=TableType.THREE_D,
        elements=6,
        scaling=scaling,
    )


class FakePlotMixin:
    """Concrete class using _GraphPlotMixin for testing.

    Provides the required attributes without any Qt/matplotlib dependencies.
    """

    def __init__(self, table, rom_definition, scaling_range=None):
        self.table = table
        self.rom_definition = rom_definition
        self._scaling_range = scaling_range
        self.data = None
        self.selected_cells = []
        self.ax_3d = None
        self.figure = None
        self.canvas = None

    # Import methods from the mixin
    from src.ui.graph_viewer import _GraphPlotMixin

    _get_scaling_range = _GraphPlotMixin._get_scaling_range
    _calculate_colors = _GraphPlotMixin._calculate_colors
    _calculate_colors_1d = _GraphPlotMixin._calculate_colors_1d


# ---------------------------------------------------------------------------
# Tests: _get_scaling_range
# ---------------------------------------------------------------------------


class TestGetScalingRange:
    def _patch_colormap(self):
        """Return a context manager that patches get_colormap to use built-in."""
        cmap = ColorMap()  # built-in
        return patch("src.utils.colormap.get_colormap", return_value=cmap)

    def test_returns_min_max_from_scaling(self):
        defn = _make_definition({"S": _make_scaling("S", 10.0, 200.0)})
        table = _make_table("S")
        obj = FakePlotMixin(table, defn)
        result = obj._get_scaling_range()
        assert result == (10.0, 200.0)

    def test_returns_none_for_zero_range(self):
        defn = _make_definition({"S": _make_scaling("S", 0.0, 0.0)})
        table = _make_table("S")
        obj = FakePlotMixin(table, defn)
        result = obj._get_scaling_range()
        assert result is None

    def test_returns_none_for_equal_min_max(self):
        defn = _make_definition({"S": _make_scaling("S", 50.0, 50.0)})
        table = _make_table("S")
        obj = FakePlotMixin(table, defn)
        result = obj._get_scaling_range()
        assert result is None

    def test_returns_none_when_no_scaling(self):
        defn = _make_definition({})
        table = _make_table("NonExistent")
        obj = FakePlotMixin(table, defn)
        result = obj._get_scaling_range()
        assert result is None

    def test_returns_none_when_no_table(self):
        defn = _make_definition()
        obj = FakePlotMixin(None, defn)
        result = obj._get_scaling_range()
        assert result is None


# ---------------------------------------------------------------------------
# Tests: _calculate_colors (2D array -> RGBA array)
# ---------------------------------------------------------------------------


class TestCalculateColors:
    @pytest.fixture(autouse=True)
    def _patch_cmap(self):
        cmap = ColorMap()  # built-in gradient
        with patch("src.ui.graph_viewer.get_colormap", return_value=cmap):
            yield

    def test_output_shape_matches_input(self):
        defn = _make_definition()
        table = _make_table()
        obj = FakePlotMixin(table, defn, scaling_range=(0.0, 100.0))
        values = np.array([[0.0, 50.0], [75.0, 100.0]])
        colors = obj._calculate_colors(values)
        assert colors.shape == (2, 2, 4)  # rows x cols x RGBA

    def test_alpha_channel_is_one(self):
        defn = _make_definition()
        table = _make_table()
        obj = FakePlotMixin(table, defn, scaling_range=(0.0, 100.0))
        values = np.array([[0.0, 100.0]])
        colors = obj._calculate_colors(values)
        np.testing.assert_array_equal(colors[..., 3], 1.0)

    def test_min_value_gets_low_color(self):
        defn = _make_definition()
        table = _make_table()
        obj = FakePlotMixin(table, defn, scaling_range=(0.0, 100.0))
        values = np.array([[0.0]])
        colors = obj._calculate_colors(values)
        # At ratio 0, built-in gradient is blue (0, 0, 255) -> (0.0, 0.0, 1.0)
        assert colors[0, 0, 2] == pytest.approx(1.0, abs=0.01)  # blue channel high

    def test_max_value_gets_high_color(self):
        defn = _make_definition()
        table = _make_table()
        obj = FakePlotMixin(table, defn, scaling_range=(0.0, 100.0))
        values = np.array([[100.0]])
        colors = obj._calculate_colors(values)
        # At ratio 1.0 (index 255), built-in gradient is red (255, 0, 0)
        assert colors[0, 0, 0] == pytest.approx(1.0, abs=0.01)  # red channel high

    def test_uniform_values_get_midpoint_color(self):
        defn = _make_definition()
        table = _make_table()
        obj = FakePlotMixin(table, defn, scaling_range=None)
        values = np.array([[5.0, 5.0], [5.0, 5.0]])
        colors = obj._calculate_colors(values)
        # All same value -> ratio 0.5 for all
        # All cells should have the same color
        assert np.all(colors[0, 0] == colors[1, 1])

    def test_without_scaling_range_uses_data_range(self):
        defn = _make_definition()
        table = _make_table()
        obj = FakePlotMixin(table, defn, scaling_range=None)
        values = np.array([[0.0, 100.0]])
        colors = obj._calculate_colors(values)
        # 0.0 should map to low color (ratio 0) and 100.0 to high color (ratio 1)
        # They should be different colors
        assert not np.array_equal(colors[0, 0], colors[0, 1])

    def test_values_outside_range_are_clamped(self):
        defn = _make_definition()
        table = _make_table()
        obj = FakePlotMixin(table, defn, scaling_range=(0.0, 100.0))
        values = np.array([[-50.0, 200.0]])
        colors = obj._calculate_colors(values)
        # -50 should clamp to ratio 0 (same as 0)
        # 200 should clamp to ratio 1 (same as 100)
        values_clamped = np.array([[0.0, 100.0]])
        colors_clamped = obj._calculate_colors(values_clamped)
        np.testing.assert_array_almost_equal(colors, colors_clamped)


# ---------------------------------------------------------------------------
# Tests: _calculate_colors_1d
# ---------------------------------------------------------------------------


class TestCalculateColors1D:
    @pytest.fixture(autouse=True)
    def _patch_cmap(self):
        cmap = ColorMap()  # built-in gradient
        with patch("src.ui.graph_viewer.get_colormap", return_value=cmap):
            yield

    def test_returns_list_of_tuples(self):
        defn = _make_definition()
        table = _make_table()
        obj = FakePlotMixin(table, defn, scaling_range=(0.0, 100.0))
        values = np.array([0.0, 50.0, 100.0])
        colors = obj._calculate_colors_1d(values)
        assert isinstance(colors, list)
        assert len(colors) == 3
        for c in colors:
            assert isinstance(c, tuple)
            assert len(c) == 3  # RGB (no alpha)

    def test_min_value_is_blue(self):
        defn = _make_definition()
        table = _make_table()
        obj = FakePlotMixin(table, defn, scaling_range=(0.0, 100.0))
        values = np.array([0.0])
        colors = obj._calculate_colors_1d(values)
        # Blue channel should be high at ratio 0
        assert colors[0][2] == pytest.approx(1.0, abs=0.01)

    def test_max_value_is_red(self):
        defn = _make_definition()
        table = _make_table()
        obj = FakePlotMixin(table, defn, scaling_range=(0.0, 100.0))
        values = np.array([100.0])
        colors = obj._calculate_colors_1d(values)
        # Red channel should be high at ratio 1.0
        assert colors[0][0] == pytest.approx(1.0, abs=0.01)

    def test_uniform_values_same_color(self):
        defn = _make_definition()
        table = _make_table()
        obj = FakePlotMixin(table, defn, scaling_range=None)
        values = np.array([42.0, 42.0, 42.0])
        colors = obj._calculate_colors_1d(values)
        assert colors[0] == colors[1] == colors[2]

    def test_without_scaling_range_uses_data_range(self):
        defn = _make_definition()
        table = _make_table()
        obj = FakePlotMixin(table, defn, scaling_range=None)
        values = np.array([10.0, 90.0])
        colors = obj._calculate_colors_1d(values)
        # First should be "low" color, second should be "high" color
        assert colors[0] != colors[1]
