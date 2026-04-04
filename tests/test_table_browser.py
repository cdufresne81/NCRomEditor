"""
Tests for TableBrowser filtering, search, and selection logic.

Requires QApplication for widget instantiation.
"""

import pytest
from unittest.mock import patch, MagicMock

from PySide6.QtWidgets import QApplication

from src.core.rom_definition import (
    RomDefinition,
    RomID,
    Scaling,
    Table,
    TableType,
)
from src.ui.table_browser import TableBrowser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for Qt widget tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _make_romid():
    return RomID(
        xmlid="test_rom",
        internalidaddress="0x0",
        internalidstring="TEST",
        ecuid="",
        make="",
        model="",
        flashmethod="",
        memmodel="",
        checksummodule="",
    )


def _make_definition(tables):
    """Create a RomDefinition with the given tables."""
    return RomDefinition(romid=_make_romid(), tables=tables)


def _make_table(name, address, category="General", level=1, ttype=TableType.TWO_D):
    return Table(
        name=name,
        address=address,
        type=ttype,
        elements=10,
        scaling="TestScaling",
        level=level,
        category=category,
    )


@pytest.fixture
def sample_tables():
    """A small set of tables across categories and levels."""
    return [
        _make_table("Fuel Map", "1000", category="Fuel", level=1),
        _make_table("Fuel Trim", "1100", category="Fuel", level=3),
        _make_table("Timing Advance", "2000", category="Ignition", level=2),
        _make_table(
            "Boost Target", "3000", category="Turbo", level=4, ttype=TableType.THREE_D
        ),
        _make_table(
            "Idle Speed", "4000", category="Idle", level=1, ttype=TableType.ONE_D
        ),
    ]


@pytest.fixture
def mock_settings():
    """Mock get_settings to avoid QSettings side effects in tests."""
    mock = MagicMock()
    mock.get_show_type_column.return_value = True
    mock.get_show_address_column.return_value = True
    with patch("src.ui.table_browser.get_settings", return_value=mock):
        yield mock


@pytest.fixture
def browser(qapp, sample_tables, mock_settings):
    """Create a TableBrowser loaded with sample tables."""
    b = TableBrowser()
    definition = _make_definition(sample_tables)
    b.load_definition(definition)
    return b


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _visible_table_names(browser):
    """Return set of visible (not hidden) table names in the tree."""
    names = set()
    for i in range(browser.tree.topLevelItemCount()):
        cat = browser.tree.topLevelItem(i)
        for j in range(cat.childCount()):
            child = cat.child(j)
            if not child.isHidden():
                names.add(child.text(0))
    return names


def _all_table_names(browser):
    """Return set of all table names regardless of visibility."""
    names = set()
    for i in range(browser.tree.topLevelItemCount()):
        cat = browser.tree.topLevelItem(i)
        for j in range(cat.childCount()):
            names.add(cat.child(j).text(0))
    return names


# ---------------------------------------------------------------------------
# Tests: load_definition populates tree
# ---------------------------------------------------------------------------


class TestLoadDefinition:
    def test_all_tables_loaded(self, browser, sample_tables):
        all_names = _all_table_names(browser)
        for t in sample_tables:
            assert t.name in all_names

    def test_categories_created(self, browser):
        categories = set()
        for i in range(browser.tree.topLevelItemCount()):
            categories.add(browser.tree.topLevelItem(i).text(0))
        assert "Fuel" in categories
        assert "Ignition" in categories
        assert "Turbo" in categories
        assert "Idle" in categories


# ---------------------------------------------------------------------------
# Tests: _filter_tables with search text
# ---------------------------------------------------------------------------


class TestSearchFilter:
    def test_search_by_name_substring(self, browser):
        browser._filter_tables("fuel")
        visible = _visible_table_names(browser)
        assert "Fuel Map" in visible
        assert "Fuel Trim" in visible
        # Non-matching tables hidden
        assert "Timing Advance" not in visible

    def test_search_by_type(self, browser):
        browser._filter_tables("3D")
        visible = _visible_table_names(browser)
        assert "Boost Target" in visible
        assert "Fuel Map" not in visible

    def test_search_by_address(self, browser):
        browser._filter_tables("0x2000")
        visible = _visible_table_names(browser)
        assert "Timing Advance" in visible
        assert "Fuel Map" not in visible

    def test_search_by_category_shows_all_children(self, browser):
        """Searching for a category name shows all tables in that category."""
        browser._filter_tables("fuel")
        visible = _visible_table_names(browser)
        assert "Fuel Map" in visible
        assert "Fuel Trim" in visible

    def test_empty_search_shows_all(self, browser):
        browser._filter_tables("fuel")
        browser._filter_tables("")
        visible = _visible_table_names(browser)
        all_names = _all_table_names(browser)
        assert visible == all_names

    def test_search_case_insensitive(self, browser):
        browser._filter_tables("IDLE")
        visible = _visible_table_names(browser)
        assert "Idle Speed" in visible


# ---------------------------------------------------------------------------
# Tests: Level filter
# ---------------------------------------------------------------------------


class TestLevelFilter:
    def test_level_0_shows_all(self, browser):
        browser.current_level_filter = 0
        browser._filter_tables("")
        visible = _visible_table_names(browser)
        all_names = _all_table_names(browser)
        assert visible == all_names

    def test_level_1_hides_higher(self, browser):
        browser.current_level_filter = 1
        browser._filter_tables("")
        visible = _visible_table_names(browser)
        assert "Fuel Map" in visible
        assert "Idle Speed" in visible
        assert "Fuel Trim" not in visible  # level 3
        assert "Boost Target" not in visible  # level 4

    def test_level_2_includes_1_and_2(self, browser):
        browser.current_level_filter = 2
        browser._filter_tables("")
        visible = _visible_table_names(browser)
        assert "Fuel Map" in visible  # level 1
        assert "Timing Advance" in visible  # level 2
        assert "Fuel Trim" not in visible  # level 3

    def test_level_filter_combined_with_search(self, browser):
        browser.current_level_filter = 1
        browser._filter_tables("fuel")
        visible = _visible_table_names(browser)
        assert "Fuel Map" in visible  # matches search AND level 1
        assert "Fuel Trim" not in visible  # matches search but level 3


# ---------------------------------------------------------------------------
# Tests: Modified-only filter
# ---------------------------------------------------------------------------


class TestModifiedFilter:
    def test_modified_only_shows_nothing_when_none_modified(self, browser):
        browser._modified_only = True
        browser._filter_tables("")
        visible = _visible_table_names(browser)
        assert len(visible) == 0

    def test_modified_only_shows_modified_table(self, browser):
        browser.modified_tables.add("1000")  # Fuel Map
        browser._modified_only = True
        browser._filter_tables("")
        visible = _visible_table_names(browser)
        assert "Fuel Map" in visible
        assert "Fuel Trim" not in visible

    def test_modified_combined_with_level(self, browser):
        browser.modified_tables.add("1000")  # Fuel Map, level 1
        browser.modified_tables.add("1100")  # Fuel Trim, level 3
        browser._modified_only = True
        browser.current_level_filter = 1
        browser._filter_tables("")
        visible = _visible_table_names(browser)
        assert "Fuel Map" in visible
        assert "Fuel Trim" not in visible  # modified but wrong level


# ---------------------------------------------------------------------------
# Tests: update_modified_tables_by_address
# ---------------------------------------------------------------------------


class TestUpdateModifiedTables:
    def test_replaces_previous_set(self, browser):
        browser.modified_tables.add("1000")
        browser.update_modified_tables_by_address(["2000", "3000"])
        assert "1000" not in browser.modified_tables
        assert "2000" in browser.modified_tables
        assert "3000" in browser.modified_tables

    def test_empty_list_clears(self, browser):
        browser.modified_tables.add("1000")
        browser.update_modified_tables_by_address([])
        assert len(browser.modified_tables) == 0


# ---------------------------------------------------------------------------
# Tests: select_table_by_address
# ---------------------------------------------------------------------------


class TestSelectTableByAddress:
    def test_selects_existing_table(self, browser):
        found = browser.select_table_by_address("0x2000")
        assert found is True
        current = browser.tree.currentItem()
        assert current is not None
        assert current.text(0) == "Timing Advance"

    def test_selects_without_0x_prefix(self, browser):
        found = browser.select_table_by_address("3000")
        assert found is True
        current = browser.tree.currentItem()
        assert current.text(0) == "Boost Target"

    def test_returns_false_for_missing_address(self, browser):
        found = browser.select_table_by_address("0xFFFF")
        assert found is False

    def test_case_insensitive_address(self, browser):
        found = browser.select_table_by_address("0x1000")
        assert found is True


# ---------------------------------------------------------------------------
# Tests: Column visibility
# ---------------------------------------------------------------------------


class TestColumnVisibility:
    def test_columns_visible_by_default(self, browser, mock_settings):
        mock_settings.get_show_type_column.return_value = True
        mock_settings.get_show_address_column.return_value = True
        browser.apply_column_visibility()
        assert not browser.tree.isColumnHidden(1)
        assert not browser.tree.isColumnHidden(2)

    def test_hide_type_column(self, browser, mock_settings):
        mock_settings.get_show_type_column.return_value = False
        mock_settings.get_show_address_column.return_value = True
        browser.apply_column_visibility()
        assert browser.tree.isColumnHidden(1)
        assert not browser.tree.isColumnHidden(2)

    def test_hide_address_column(self, browser, mock_settings):
        mock_settings.get_show_type_column.return_value = True
        mock_settings.get_show_address_column.return_value = False
        browser.apply_column_visibility()
        assert not browser.tree.isColumnHidden(1)
        assert browser.tree.isColumnHidden(2)
