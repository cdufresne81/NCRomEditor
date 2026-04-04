# Code Audit — 2026-04-03

Full-codebase audit performed with all ~42K lines loaded into a single 1M-token context.

## Bugs

### 1. `select_all_data` skips first data row in 3D tables
- **File:** `src/ui/table_viewer_helpers/operations.py:509-519`
- **Impact:** Ctrl+A on a 3D table misses the first data row
- **Cause:** Stale comment ("Row 0: Axis labels, Row 1: X-axis values") — actual layout is Row 0: X-axis values, Row 1+: data. Selection starts at row 2 instead of row 1.

### 2. `display_to_raw` bypasses `^` to `**` conversion
- **File:** `src/ui/table_viewer_helpers/editing.py:138-151` and `:321-334`
- **Impact:** Cell editing would fail with TypeError on any scaling whose `frexpr` uses `^` (calculator-style exponentiation)
- **Cause:** Calls `simple_eval(scaling.frexpr)` directly instead of using `ScalingConverter.from_display()` which pre-converts `^` to `**`.

### 3. X-axis data read twice in interleaved 3D
- **File:** `src/core/rom_reader.py:522-534`
- **Impact:** Wasted computation (no data corruption)
- **Cause:** `_read_interleaved_3d()` reads `x_raw` unconditionally, then reads it again identically inside the `if x_axis:` block.

### 4. Version-compare window cleanup attribute mismatch
- **File:** `src/ui/compare_window.py:1376-1378` vs `src/ui/project_mixin.py:375`
- **Impact:** Version comparison windows don't clean up their reference on the history dialog
- **Cause:** `closeEvent` checks `hasattr(parent, "compare_window")` but the dialog stores it as `_compare_window` (with underscore).

---

## Dead Code

### 5. ~385 lines of dead methods in `flash_mixin.py`
Superseded by `ecu_window.py`. Dead methods: `_FlashWorker`, `FlashProgressDialog`, `_on_flash_rom`, `_on_read_rom`, `_on_read_rom_finished`, `_on_clear_dtcs`, `_on_ecu_info`, `_run_flash_operation`. The `_on_flash_rom` method imports nonexistent `flash_setup_dialog.py`.

### 6. `GraphViewer` class never imported
- **File:** `src/ui/graph_viewer.py:523-594`
- Only `GraphWidget` is used (by `TableViewerWindow`).

### 7. Dead orange selection CSS in display helper
- **File:** `src/ui/table_viewer_helpers/display.py:97-107`
- Never applied. Viewer uses blue selection from `_apply_table_style_internal`.

### 8. `_apply_table_style` method never called externally
- **File:** `src/ui/table_viewer.py:428-432`
- Delegates to display helper but no code path invokes it.

### 9. Inline `Path` re-import
- **File:** `main.py:617-618`
- `from pathlib import Path as _Path` inside `_find_document_by_rom_path` — `Path` already imported at module level.

### 10. `run-mcp.bat` reference to nonexistent file
- **File:** `src/ui/mcp_mixin.py:157-160`

---

## Code Duplication

### 11. `_FlashWorker` duplicated
- `src/ui/flash_mixin.py:48-91` and `src/ui/ecu_window.py:53-105` — near-identical classes.

### 12. `handle_rom_operation_error` duplicated
- `main.py:82-93` and `src/ui/project_mixin.py:42-46` — identical function.

### 13. DTC read/clear logic duplicated
- `flash_mixin.py:387-428` and `ecu_window.py:975-1044` — same read, deduplicate, display pattern.

### 14. `_auto_save_rom` / `_auto_save_ram_dump` near-identical
- `ecu_window.py:925-971` — only the filename prefix differs.

### 15. `_make_icon` / `_make_toolbar_icon` trivial wrappers
- `main.py:588-590` and `table_viewer_window.py:466-468` — both just call `make_icon(self, name)`.

### 16. Table style CSS duplicated 3 times
- `table_viewer.py:439-451`, `display.py:94-108`, `compare_window.py:593-601` — with slight selection color variations.

---

## Test & Tooling Issues

### 17. `coverage.xml` in repo root
7,818-line generated file. Should be in `.gitignore`.

### 18. Coverage forced on every pytest run
`pytest.ini` addopts includes `--cov=src --cov-report=term-missing --cov-report=html --cov-report=xml`. Slows every run.

### 19. Debug GUI scripts committed
9+ files in `tests/gui/` with names like `debug_*`, `*_investigate`, `*_issue` — one-off debugging artifacts.

### 20. `test_runner.py:870` references nonexistent `main_window.table_browser`
`set_level_filter()` would crash at runtime. Each `RomDocument` has its own table browser.

### 21. ~6,000 lines of UI code with zero test coverage
`compare_window.py`, `ecu_window.py`, `table_viewer_window.py`, `graph_viewer.py`, `settings_dialog.py`, `table_browser.py`, `history_viewer.py`, `project_wizard.py`, `icons.py`.

---

## Stale Documentation

### 22. README version wrong
`README.md:334` says v2.3.0, actual latest is v2.6.1.

### 23. README project structure incomplete
Missing files added since v2.3.0.

### 24. `thinking-pad.md` committed to repo
Personal brainstorming notes that belong in personal workspace, not repository.

---

## Design Notes (deferred, not actionable now)

- MainWindow has 5 mixins creating complex MRO
- Mutable shared dicts (`modified_cells`, `original_table_values`) as pseudo-global state
- 4-hop signal chain for cell edits
- Null-byte composite key separator (`\0`) in table_undo_manager
- Compare window reimplements ~290 lines of table display logic from display helper
- Two parallel flash UI implementations (FlashMixin + ECUProgrammingWindow)
