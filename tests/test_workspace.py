"""
Tests for workspace directory feature.

Tests workspace defaults, path derivation, and migration.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.utils.settings import AppSettings


@pytest.fixture
def mock_qsettings():
    """Mock QSettings to avoid writing to actual system settings"""
    with patch("src.utils.settings.QSettings") as mock:
        settings_store = {}

        def mock_value(key, default=None, type=None):
            val = settings_store.get(key, default)
            if type is bool and not isinstance(val, bool):
                return default
            return val

        def mock_set_value(key, value):
            settings_store[key] = value

        mock_instance = MagicMock()
        mock_instance.value = mock_value
        mock_instance.setValue = mock_set_value
        mock_instance.sync = MagicMock()
        mock.return_value = mock_instance

        yield mock_instance, settings_store


@pytest.fixture
def app_settings(mock_qsettings):
    return AppSettings()


class TestWorkspaceDirectory:
    """Tests for workspace root directory setting."""

    def test_default_workspace_is_user_data_dir(self, app_settings):
        result = app_settings.get_workspace_directory()
        # Default workspace should be the user data dir
        assert result
        assert Path(result).name == "NCFlash" or "NCFlash" in result

    def test_set_and_get_workspace(self, mock_qsettings):
        _, store = mock_qsettings
        s = AppSettings()
        s.set_workspace_directory("/custom/workspace")
        assert s.get_workspace_directory() == os.path.normpath("/custom/workspace")


class TestPathsDeriveFromWorkspace:
    """Tests that path settings derive defaults from workspace root."""

    def test_projects_derives_from_workspace(self, mock_qsettings):
        _, store = mock_qsettings
        s = AppSettings()
        s.set_workspace_directory("/my/workspace")
        result = s.get_projects_directory()
        expected = os.path.normpath("/my/workspace/projects")
        assert result == expected

    def test_exports_derives_from_workspace(self, mock_qsettings):
        _, store = mock_qsettings
        s = AppSettings()
        s.set_workspace_directory("/my/workspace")
        result = s.get_export_directory()
        expected = os.path.normpath("/my/workspace/exports")
        assert result == expected

    def test_metadata_derives_from_workspace(self, mock_qsettings):
        _, store = mock_qsettings
        s = AppSettings()
        s.set_workspace_directory("/my/workspace")
        result = s.get_metadata_directory()
        expected = os.path.normpath("/my/workspace/metadata")
        assert result == expected

    def test_colormaps_derives_from_workspace(self, mock_qsettings):
        _, store = mock_qsettings
        s = AppSettings()
        s.set_workspace_directory("/my/workspace")
        result = s.get_colormap_directory()
        expected = os.path.normpath("/my/workspace/colormaps")
        assert result == expected

    def test_roms_derives_from_workspace(self, mock_qsettings):
        _, store = mock_qsettings
        s = AppSettings()
        s.set_workspace_directory("/my/workspace")
        result = s.get_roms_directory()
        expected = os.path.normpath("/my/workspace/roms")
        assert result == expected

    def test_screenshots_derives_from_workspace(self, mock_qsettings):
        _, store = mock_qsettings
        s = AppSettings()
        s.set_workspace_directory("/my/workspace")
        result = s.get_screenshots_directory()
        expected = os.path.normpath("/my/workspace/screenshots")
        assert result == expected

    def test_reads_derives_from_workspace(self, mock_qsettings):
        _, store = mock_qsettings
        s = AppSettings()
        s.set_workspace_directory("/my/workspace")
        result = s.get_reads_directory()
        expected = os.path.normpath("/my/workspace/reads")
        assert result == expected


class TestPathOverrides:
    """Tests that individual path settings override workspace defaults."""

    def test_explicit_projects_overrides_workspace(self, mock_qsettings):
        _, store = mock_qsettings
        s = AppSettings()
        s.set_workspace_directory("/my/workspace")
        s.set_projects_directory("/elsewhere/projects")
        assert s.get_projects_directory() == os.path.normpath("/elsewhere/projects")

    def test_explicit_roms_overrides_workspace(self, mock_qsettings):
        _, store = mock_qsettings
        s = AppSettings()
        s.set_workspace_directory("/my/workspace")
        s.set_roms_directory("/elsewhere/roms")
        assert s.get_roms_directory() == os.path.normpath("/elsewhere/roms")

    def test_explicit_screenshots_overrides_workspace(self, mock_qsettings):
        _, store = mock_qsettings
        s = AppSettings()
        s.set_workspace_directory("/my/workspace")
        s.set_screenshots_directory("/elsewhere/screenshots")
        assert s.get_screenshots_directory() == os.path.normpath(
            "/elsewhere/screenshots"
        )


class TestEnsureWorkspaceDirectories:
    """Tests for workspace directory creation."""

    def test_creates_all_subdirectories(self, tmp_path, mock_qsettings):
        _, store = mock_qsettings
        s = AppSettings()
        s.set_workspace_directory(str(tmp_path / "ws"))

        from src.utils.workspace import ensure_workspace_directories

        with patch("src.utils.workspace.get_settings", return_value=s):
            ensure_workspace_directories()

        ws = tmp_path / "ws"
        assert (ws / "roms").is_dir()
        assert (ws / "projects").is_dir()
        assert (ws / "metadata").is_dir()
        assert (ws / "exports").is_dir()
        assert (ws / "screenshots").is_dir()
        assert (ws / "colormaps").is_dir()
        assert (ws / "reads").is_dir()

    def test_migration_copies_metadata(self, tmp_path, mock_qsettings):
        _, store = mock_qsettings
        s = AppSettings()
        s.set_workspace_directory(str(tmp_path / "ws"))

        # Create fake app root with metadata
        app_root = tmp_path / "app"
        (app_root / "examples" / "metadata").mkdir(parents=True)
        (app_root / "examples" / "metadata" / "test.xml").write_text("<rom/>")

        from src.utils.workspace import ensure_workspace_directories

        with (
            patch("src.utils.workspace.get_settings", return_value=s),
            patch("src.utils.workspace.get_app_root", return_value=app_root),
        ):
            ensure_workspace_directories()

        assert (tmp_path / "ws" / "metadata" / "test.xml").exists()

    def test_migration_runs_only_once(self, tmp_path, mock_qsettings):
        _, store = mock_qsettings
        s = AppSettings()
        s.set_workspace_directory(str(tmp_path / "ws"))

        # Simulate migration already done
        store["migration/workspace_v1_done"] = True

        app_root = tmp_path / "app"
        (app_root / "examples" / "metadata").mkdir(parents=True)
        (app_root / "examples" / "metadata" / "test.xml").write_text("<rom/>")

        from src.utils.workspace import ensure_workspace_directories

        with (
            patch("src.utils.workspace.get_settings", return_value=s),
            patch("src.utils.workspace.get_app_root", return_value=app_root),
        ):
            ensure_workspace_directories()

        # File should NOT be copied since migration was already done
        assert not (tmp_path / "ws" / "metadata" / "test.xml").exists()
