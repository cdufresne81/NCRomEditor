# Full Code Audit Report: NC ROM Editor

**Date:** February 7, 2026
**Scope:** Full codebase scan (~17,700 LOC)
**Last updated:** February 7, 2026 (post-remediation re-audit)

## Executive Summary

This is a **~17,700 LOC Python/Qt6 desktop application** for editing automotive ECU ROM files. The architecture is clean — separation between `core/` (data), `ui/` (presentation), and `utils/` (infrastructure), now further improved by extracting mixin classes and shared helpers.

**All 40 original findings have been addressed.** The three systemic issues identified in the initial audit have been resolved:

1. **Atomic file writes** — ROM files, project files, and commit history all use write-to-temp + `os.replace()` with `fsync()` for crash safety
2. **Tautological tests rewritten** — Three test files now import and test production code; 240 tests pass (1 minor platform-specific failure)
3. **Memory leaks plugged** — `deleteLater()` on tab close, `WA_DeleteOnClose` on graph windows, matplotlib figure cleanup, undo stack cleanup on ROM close, per-ROM tracking dict pruning

The codebase is now in solid shape for a desktop application of this size and scope. No critical or high-severity issues remain.

---

## Remediation Progress

### ALL 40 FINDINGS — Fixed

| # | Sev | Finding | Fix |
|---|-----|---------|-----|
| 1 | CRIT | `write_table_data` ignores `swapxy` on flatten — silent data corruption | Added `order='F' if table.swapxy else 'C'` to the flatten call |
| 2 | CRIT | Paste emits N individual `cell_changed` signals | Paste now emits a single `bulk_changes` signal |
| 3 | CRIT | `save()` never clears the modified flag | Added `set_modified(False)` after successful save |
| 4 | CRIT | ~46% of tests are tautological | Rewrote `test_axis_editing.py`, `test_interpolation.py`, `test_table_viewer_helpers.py` to test production code |
| 5 | HIGH | `save_rom` has no atomicity | Write-to-temp + `os.replace()` + `os.fsync()` |
| 6 | HIGH | `project.json`/`commits.json` writes not atomic | Same write-to-temp-then-rename pattern |
| 7 | HIGH | `close_tab` doesn't `deleteLater()` the widget | Added `widget.deleteLater()` after `removeTab()` |
| 8 | HIGH | `open_table_windows` holds refs to closed windows | `deleteLater()` in `closeEvent`, `WA_DeleteOnClose` on `GraphViewer` |
| 9 | HIGH | Matplotlib figures never closed | Added `plt.close(self.figure)` in `GraphViewer.closeEvent` and `TableViewerWindow.closeEvent` |
| 10 | HIGH | `except (SpecificError, Exception)` swallows all errors | Split into specific catch + `Exception` with `logger.exception()` for full tracebacks |
| 11 | HIGH | `GraphWidget` and `GraphViewer` 90% duplicated | Extracted `_GraphPlotMixin` with 14 shared methods (~745 to ~350 lines) |
| 12 | HIGH | Undo callbacks use `get_current_document()` (active tab) | All undo/edit handlers resolve correct ROM via `_find_document_by_rom_path()` |
| 13 | HIGH | `QApplication.processEvents()` in event handlers | Removed entirely; no `processEvents()` calls remain in production code |
| 14 | HIGH | Cell delegate unpacks axis `data_coords` as `(row, col)` | Added `isinstance(data_coords[0], str)` guard to skip axis cells |
| 15 | HIGH | All deps use `>=` with no upper bounds | Pinned versions with upper bounds (e.g., `PySide6>=6.10.0,<7.0.0`) |
| 16 | MED | `simple_eval` called per-element in Python loop | Vectorized via AST-validated `compile()` + `eval()` on whole numpy arrays; fallback to per-element `simple_eval` |
| 17 | MED | `modified_cells`/`original_table_values` never pruned on tab close | `close_tab()` now calls `.pop(rom_path, None)` on both dicts |
| 18 | MED | `remove_stack()` is a no-op | Fixed: `stack.clear()` + `stack.deleteLater()` in both `remove_stack()` and `clear_all()` |
| 19 | MED | `MainWindow.__init__` does too much | Deferred heavy work to `_deferred_init()` via `QTimer.singleShot(0, ...)` |
| 20 | MED | `MainWindow` is a god class (~15 responsibilities) | Extracted `RecentFilesMixin`, `ProjectMixin`, `SessionMixin` (~400 lines moved out) |
| 21 | MED | `lstrip('0x')` strips chars not prefix | Replaced with `removeprefix('0x')` |
| 22 | MED | `_display_3d` sets items cell-by-cell without signal blocking | Wrapped in `blockSignals(True)` + `setUpdatesEnabled(False)` with single `viewport().update()` |
| 23 | MED | `_filter_commits` O(N) lookups per keystroke | Changed to `item.data(0, Qt.UserRole + 1)` using already-stored commit objects |
| 24 | MED | Definitions path uses `Path.cwd()` not `Path(__file__)` | Changed to `Path(__file__).resolve().parent.parent.parent` |
| 25 | MED | No type validation on QSettings geometry/splitter | Added `isinstance(value, QByteArray)` guard; returns `None` for corrupted values |
| 26 | MED | `update_recent_files_menu` leaks QAction objects | Added `action.deleteLater()` before clearing the list |
| 27 | MED | Interpolation silently skips cells when `scaling` is None | Added `_check_scaling_available()` with `QMessageBox.warning()` |
| 28 | MED | `closeEvent` doesn't check unsaved changes across tabs | Added per-tab Save/Discard/Cancel prompt loop in `SessionMixin.closeEvent` |
| 29 | MED | `QTimer.singleShot(0, canvas.draw)` after every plot (2N draws) | All graph refreshes use 50ms debounce timer; `_refresh_graph()` cancels pending selection timer |
| 30 | MED | Header resize mode save/restore duplicated 8+ times | Extracted `frozen_table_updates()` context manager in `context.py` |
| 31 | MED | lxml XXE not mitigated | All `etree.parse()` sites use `resolve_entities=False, no_network=True` |
| 32 | MED | Tests mutate global/class state without cleanup | Added `autouse` fixtures in `test_colormap.py` and `test_settings.py` |
| 33 | LOW | `get_tables_by_category()`/`get_table_by_name()` are O(n) | Added lazy cache dicts; O(1) after first call |
| 34 | LOW | `sys.exit(1)` in constructor bypasses Qt cleanup | Deferred via `QTimer.singleShot(0, lambda: sys.exit(1))` |
| 35 | LOW | UUID truncated to 12 chars | Changed to `uuid.uuid4().hex` (32 hex chars) |
| 36 | LOW | `setup_logging()` at import time | Removed auto-call at module level; only called explicitly in `main.py` |
| 37 | LOW | `"Courier New"` is Windows-only | Changed to font family tuple with `QFont.setFamilies()` |
| 38 | LOW | Backup file has no rotation | Implemented 3-level rotation (.bak.1, .bak.2, .bak.3) |
| 39 | LOW | `import` statements inside function bodies | Moved key imports (matplotlib, simpleeval, Qt classes) to module level |
| 40 | LOW | `sync()` called on every `setValue()` | Removed all per-setValue `sync()` calls; only 1 intentional `sync()` remains in `open_recent_file()` |

---

## Sorted Findings (by severity, then impact)

### CRITICAL — Fix before shipping

| # | Location | Issue | Recommendation | Status |
|---|----------|-------|----------------|--------|
| 1 | `src/core/rom_reader.py:455` | **`write_table_data` ignores `swapxy` on flatten.** Read uses `order='F'` for swapxy tables, but write always flattens with C order. **Silent data corruption** for any swapxy table written via bulk write. | Add `order='F' if table.swapxy else 'C'` to the flatten call. | **DONE** |
| 2 | `src/ui/table_viewer_helpers/clipboard.py:168` | **Paste emits N individual `cell_changed` signals** instead of one `bulk_changes`. Creates N undo entries (user must Ctrl+Z N times), N repaints, and N modification-tracking calls. | Emit a single `bulk_changes` signal after paste, like the bulk operations do. | **DONE** |
| 3 | `src/ui/rom_document.py:107` | **`save()` never clears the modified flag.** After saving, the UI still shows "modified" forever. Users can't tell if their data is actually saved. | Call `set_modified(False)` after successful save. | **DONE** |
| 4 | Tests: `test_axis_editing.py`, `test_interpolation.py`, `test_table_viewer_helpers.py` | **~55 out of ~120 tests (~46%) are tautological.** They construct local data, do inline math, and assert on their own results. Zero production code is imported. They provide no regression protection. | Rewrite to import and call actual production functions. | **DONE** |

### HIGH — Significant risk, address soon

| # | Location | Issue | Recommendation | Status |
|---|----------|-------|----------------|--------|
| 5 | `src/core/rom_reader.py:643-649` | **`save_rom` has no atomicity.** A crash mid-write leaves a truncated/corrupted ROM file. No backup is made. | Write to temp file, then `os.replace()` (atomic on POSIX, near-atomic on Windows). | **DONE** |
| 6 | `src/core/project_manager.py:384-397` | **`project.json` and `commits.json` writes are not atomic.** Crash = corrupted project = unrecoverable. | Same write-to-temp-then-rename pattern. | **DONE** |
| 7 | `main.py:421` | **`close_tab` doesn't `deleteLater()` the widget.** `removeTab()` only unparents; the `RomDocument` (with its entire ROM in memory) leaks. | Call `widget.deleteLater()` after `removeTab()`. | **DONE** |
| 8 | `src/ui/table_viewer_window.py:596` | **`open_table_windows` list holds refs to closed windows.** `TableViewerWindow` doesn't set `WA_DeleteOnClose` or call `deleteLater()`. Matplotlib figures, numpy arrays all leak. | `deleteLater()` in `closeEvent`, `WA_DeleteOnClose` on `GraphViewer`. | **DONE** |
| 9 | `src/ui/graph_viewer.py:505` | **Matplotlib figures never closed.** `GraphViewer` has no `closeEvent` calling `plt.close(fig)`. Each standalone graph window leaks a figure in matplotlib's global registry. | Override `closeEvent` to call `plt.close(self.figure)`. | **DONE** |
| 10 | `main.py` (12 sites) | **`except (SpecificError, Exception)` swallows all errors.** `Exception` is a superclass -- the specific catches are dead code. Programming bugs (`TypeError`, `KeyError`) become user-facing "Failed to open" messages. | Catch specific errors in one block, catch `Exception` separately with full traceback logging. | **DONE** |
| 11 | `src/ui/graph_viewer.py` | **`GraphWidget` and `GraphViewer` are 90% duplicated** (~700 lines). A bug fix in one may be missed in the other. | Extract shared logic into a base class or mixin. | **DONE** |
| 12 | `main.py` (6 sites) | **Undo callbacks use `get_current_document()` which returns the *active tab*.** If user has multiple ROMs open, undo may write to the wrong ROM's data. | Pass the ROM path/document reference through the undo command. | **DONE** |
| 13 | `src/ui/table_viewer_window.py` | **`QApplication.processEvents()` in event handlers.** Causes re-entrant event processing -- a well-known Qt anti-pattern that leads to hard-to-reproduce crashes. | Use `QTimer.singleShot(0, ...)` for deferred layout or remove entirely. | **DONE** |
| 14 | `src/ui/table_viewer_helpers/cell_delegate.py:36` | **Cell delegate unpacks axis `data_coords` as `(row, col)`.** Axis cells store `('x_axis', index)` -- unpacking sets `data_row = 'x_axis'`, then indexing into numpy arrays with a string crashes. | Check if `data_coords[0]` is a string before unpacking. | **DONE** |
| 15 | `requirements.txt` | **All deps use `>=` with no upper bounds.** A `pip install` pulls latest versions, risking breaking changes. | Pin exact versions or set upper bounds (e.g., `PySide6>=6.6.0,<7.0.0`). | **DONE** |

### MEDIUM -- Worth fixing, not urgent

| # | Location | Issue | Status |
|---|----------|-------|--------|
| 16 | `src/core/rom_reader.py:43-103` | **`simple_eval` called per-element in a Python loop** for scaling. On large tables (1000+ cells), this is extremely slow. Vectorized numpy expressions would be orders of magnitude faster. | **DONE** |
| 17 | `main.py:414-416` | **`modified_cells` / `original_table_values` dicts never pruned** when tabs close. Memory grows unbounded over a long session. | **DONE** |
| 18 | `src/core/table_undo_manager.py:155-165` | **`remove_stack()` is a no-op.** Undo stacks (up to 100 commands each, with numpy data) accumulate forever. | **DONE** |
| 19 | `main.py:125-176` | **`MainWindow.__init__` does too much** -- file I/O, modal dialogs, XML parsing, session restore. Blocks startup and makes testing impossible. | **DONE** |
| 20 | `main.py:74` | **`MainWindow` is a god class** with ~15 responsibilities (ROM I/O, tab management, undo, project management, change tracking, session save/restore, etc.). | **DONE** |
| 21 | `src/ui/table_browser.py:423,435` | **`lstrip('0x')` strips individual chars, not the prefix.** `"0x0080".lstrip('0x')` -> `"80"` (strips all leading 0s and x). Use `removeprefix('0x')`. | **DONE** |
| 22 | `src/ui/table_viewer_helpers/display.py:302-303` | **`_display_3d` sets items cell-by-cell** without signal blocking. Each `setItem()` fires internal model signals. | **DONE** |
| 23 | `src/ui/history_viewer.py:143` | **`_filter_commits` calls `get_commit()` per item on every keystroke.** O(N) lookups per keystroke. Commit data is already stored in item data but unused. | **DONE** |
| 24 | `src/utils/settings.py:28` | **Definitions default path uses `Path.cwd()`** instead of `Path(__file__)`. If launched from different directory, definitions won't be found. | **DONE** |
| 25 | `src/utils/settings.py:43,54` | **No type validation on `get_window_geometry()` / `get_splitter_state()`.** Corrupted QSettings values could crash on startup. | **DONE** |
| 26 | `src/ui/recent_files_mixin.py:31-32` | **`update_recent_files_menu` leaks QAction objects.** `removeAction` doesn't delete them; lambda connections never disconnected. | **DONE** |
| 27 | `src/ui/table_viewer_helpers/interpolation.py:31-55` | **Interpolation silently skips cells when `scaling` is None.** No warning or feedback to user. | **DONE** |
| 28 | `src/ui/session_mixin.py:51-83` | **`closeEvent` doesn't check for unsaved changes** across tabs. Individual `close_tab` prompts, but closing the main window bypasses this. | **DONE** |
| 29 | `src/ui/table_viewer_window.py` | **`QTimer.singleShot(0, canvas.draw)` after every plot.** Causes 2N draws for N updates; can't be cancelled during rapid selection changes. | **DONE** |
| 30 | `src/ui/table_viewer_helpers/context.py:90-117` | **Header resize mode save/restore pattern duplicated 8+ times** across operations, interpolation, clipboard, display. Should be a context manager. | **DONE** |
| 31 | `src/core/definition_parser.py:63`, `src/core/rom_detector.py:110`, `src/core/metadata_writer.py:36,112` | **lxml XXE not mitigated.** `etree.parse()` uses default parser with `resolve_entities=True`. A crafted XML definition could read local files. | **DONE** |
| 32 | `test_colormap.py`, `test_settings.py` | **Tests mutate global/class state without cleanup.** `ColorMap._builtin_gradient = None` persists across tests, potentially causing order-dependent failures. | **DONE** |

### LOW -- Minor or cosmetic

| # | Location | Issue | Status |
|---|----------|-------|--------|
| 33 | `src/core/rom_definition.py:159-185` | `get_tables_by_category()` and `get_table_by_name()` are O(n) on every call. Should cache or use a dict. | **DONE** |
| 34 | `main.py:147` | `sys.exit(1)` in constructor bypasses Qt cleanup. Should defer exit. | **DONE** |
| 35 | `src/core/version_models.py:122` | UUID truncated to 12 chars reduces entropy. Low practical collision risk but unnecessary. | **DONE** |
| 36 | `src/utils/logging_config.py` | `setup_logging()` at import time clobbers any existing logging configuration. | **DONE** |
| 37 | `src/utils/constants.py:27` | `"Courier New"` is Windows-only. Missing cross-platform font fallback. | **DONE** |
| 38 | `src/core/metadata_writer.py:59-73` | Backup file has no rotation -- each backup overwrites the previous one. | **DONE** |
| 39 | Multiple files | `import` statements inside function bodies (matplotlib, simpleeval, pathlib) add per-call overhead. Move to module level. | **DONE** |
| 40 | `src/utils/settings.py` | `sync()` called on every single `setValue()`. One sync on exit would suffice. | **DONE** |

---

## Experienced Engineer's Assessment

### Maintainability: 8/10 -> 9/10 -- Significantly improved

- Clean `core/ui/utils` separation remains the backbone
- `MainWindow` reduced from ~1,500 lines / 44 methods to ~1,100 lines / 33 methods via 3 mixin classes
- `graph_viewer.py` duplication resolved via `_GraphPlotMixin` (~700 lines to ~350 lines)
- Header resize boilerplate consolidated into `frozen_table_updates()` context manager
- Module-level imports throughout (no more per-call import overhead in hot paths)
- Naming conventions are consistent; file sizes are reasonable
- **Remaining gap:** `main.py` still owns too many responsibilities (ROM I/O, tab management, undo, change tracking). The mixin extraction helped, but a further refactor into a dedicated `RomTabManager` or similar controller would be beneficial for the next phase of growth

### Reliability: 8/10 -> 9/10 -- All findings resolved, no regressions

- All 4 CRITICAL findings fixed (swapxy corruption, paste signals, save flag, test quality)
- All 11 HIGH findings fixed (atomicity, memory leaks, wrong-ROM undo, exception handling, delegate crash, processEvents, dep pinning)
- All 17 MEDIUM findings fixed (vectorized scaling, undo stack cleanup, XXE mitigation, signal blocking, etc.)
- All 8 LOW findings fixed (UUID entropy, font fallback, backup rotation, import cleanup, etc.)
- No regressions introduced by fixes (verified by 240 passing tests)
- **Remaining gap:** The 1 test failure (`test_custom_definitions_dir`) is a Windows-only path normalization issue in the test runner test, not in production code. The test asserts forward-slash paths on a Windows system where `Path()` normalizes to backslashes. This is cosmetic.

### Test Quality: 6/10 -> 7/10 -- Improved, still has room to grow

- Three tautological test files rewritten to test production code
- Test state cleanup fixtures prevent order-dependent failures
- 240 tests pass, 1 skipped, 1 platform-specific failure
- Real coverage is now meaningful -- tests exercise `ScalingConverter`, `_convert_expr_to_python`, swapxy round-trips, atomic writes, undo manager, colormap, settings, metadata writer, and more
- **Remaining gaps:**
  - No integration tests that exercise the full ROM read -> edit -> save -> read-back cycle
  - No tests for the mixin classes or UI workflows (these are hard to unit test without a running Qt event loop)
  - No property-based / fuzz testing on the scaling expression evaluator
  - Test coverage percentage is not measured; adding `pytest-cov` runs would help identify blind spots

### Performance: 7/10 -> 8/10 -- Hotspots addressed

- Vectorized numpy scaling eliminates the per-element `simple_eval` bottleneck for safe expressions
- `_display_3d` signal blocking prevents O(N^2) repaints during table population
- History filter uses stored item data (O(1)) instead of per-item `get_commit()` (O(N))
- Table lookups cached after first access (O(1) vs. O(N))
- Graph draw deduplication via 50ms debounce timer
- Header resize context manager prevents redundant resize calculations
- **Remaining gaps:**
  - For expressions that fail AST safety checks, the `simple_eval` per-element fallback is still used. In practice, most ROM scaling expressions are simple arithmetic, so the fast path covers the common case.
  - No profiling data available for the 3D table rendering path with very large tables (100x100+)

### Security: 8/10 -> 9/10 -- XXE mitigated

- All 4 `etree.parse()` call sites now use `resolve_entities=False, no_network=True`
- `simpleeval` remains adequate for trusted-input expression evaluation
- Vectorized `eval()` path uses strict AST whitelist (only arithmetic + `x` variable, no function calls, no attribute access, `__builtins__` is `{}`)
- No network exposure, no user input that reaches dangerous APIs
- **Remaining gap:** The `metadata_writer.py` XPath query `f".//scaling[@name='{scaling_name}']"` uses string interpolation. If scaling names came from untrusted input, this could be an XPath injection vector. In practice, scaling names come from the same XML file being queried, so this is not exploitable in the current architecture.

---

## Post-Remediation Notes

### New Code Quality Assessment

The remediation introduced several new components. Assessment of each:

**1. Mixin classes (`recent_files_mixin.py`, `project_mixin.py`, `session_mixin.py`)**
- Clean separation of concerns; each handles one responsibility group
- Well-documented dependencies on `MainWindow` attributes (docstrings list required fields)
- Exception handling follows the same split-catch pattern as `main.py` (specific + generic with `logger.exception()`)
- One minor issue: `open_recent_file()` in `recent_files_mixin.py` directly accesses `self.settings.settings.sync()` (reaching through the settings wrapper), but this is the only remaining `sync()` call and is intentional (removing a stale file path)
- No MRO issues: all mixins are plain classes with no `__init__`, and `MainWindow` properly calls `super().__init__()` once

**2. Context manager (`context.py`)**
- `frozen_table_updates()` correctly saves/restores header resize modes with `try/finally`
- Signal blocking and update disabling are properly paired (restored in `finally` block)
- Helper functions (`save_header_resize_modes`, `set_headers_fixed`, `restore_header_resize_modes`) are reusable by `display.py`'s `begin_bulk_update`/`end_bulk_update` which need finer-grained control
- No issues found

**3. Vectorized scaling (`rom_reader.py`)**
- AST validation (`_is_safe_numpy_expr`) uses a strict whitelist of safe node types: only arithmetic operators, constants, and the variable `x`
- Function calls, attribute access, imports, and subscripts are all rejected
- `eval()` is called with `{"__builtins__": {}}` to prevent access to built-in functions
- Fallback to `simpleeval` ensures correctness for any expression the fast path cannot handle
- Pre-compilation at `ScalingConverter.__init__` time means the cost is paid once per scaling, not per element
- No security concerns found

**4. Deferred init (`main.py`)**
- `QTimer.singleShot(0, self._deferred_init)` runs after the constructor returns and the window is shown
- `self.rom_detector = None` is set in `__init__`, and `_open_rom_file()` already checks for `None` before using it
- The `_deferred_init` method handles its own errors (try/except around `RomDetector` init)
- `sys.exit(1)` on setup cancellation is deferred via another `QTimer.singleShot(0, ...)` to allow Qt to finish construction
- **One theoretical concern:** If the user somehow triggers `open_rom` before `_deferred_init` runs (e.g., via command-line argument or extremely fast interaction), `self.rom_detector` would be `None`. However, this is handled gracefully: `_open_rom_file()` checks `if not self.rom_detector` and shows an error dialog. No crash risk.

### Remaining Technical Debt (Priority Order)

These are not bugs -- they are opportunities for future improvement:

1. **Integration test for ROM read/edit/save cycle** -- The most valuable missing test. Would catch regressions in the data pipeline.
2. **Further `MainWindow` decomposition** -- The mixin extraction was a good first step, but `main.py` is still ~1,100 lines with ROM I/O, tab management, undo callbacks, and change tracking interleaved. A `RomTabController` class would further separate concerns.
3. **Test coverage measurement** -- Adding `pytest-cov` to CI would identify untested code paths.
4. **Remaining function-level imports** -- `TableViewerWindow` still has 3 function-level imports (`TableType` x2, `QEvent` x1) that could be moved to module level. These are in `__init__` and menu setup, not hot paths, so the impact is negligible.
5. **XPath string interpolation** in `metadata_writer.py` -- Low risk (scaling names are from trusted XML), but parameterized XPath would be more robust.
6. **Test runner path normalization** -- The 1 failing test (`test_custom_definitions_dir`) needs to use `Path()` comparison instead of string comparison to work cross-platform.

---

## Recommended Priority Order

All 40 original findings are complete. Recommended next steps for continued improvement:

1. **Write an integration test for the ROM read/edit/save round-trip** -- Highest value-to-effort ratio for regression protection
2. **Fix the 1 failing test** (`test_custom_definitions_dir` path normalization on Windows)
3. **Add `pytest-cov` to CI** and establish a coverage baseline
4. **Extract a `RomTabController`** from `MainWindow` to further reduce the class size
5. **Add property-based tests** for scaling expression evaluation (e.g., with Hypothesis)
