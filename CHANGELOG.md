# Changelog

All notable changes to NC ROM Editor are documented here.

## [v1.3.0] - 2026-02-28

### Added
- **Windows installer** — Inno Setup installer with Start Menu shortcut, optional Desktop shortcut, and uninstaller
- **PyInstaller packaging** — Standalone Windows exe build via `build.bat`, no Python required to run
- **Flash ROM to ECU** — One-click flash via RomDrop integration (`Ctrl+Shift+F`) with safety warning dialog
- **RomDrop settings** — Configurable RomDrop executable path in Settings > Tools
- **GitHub Actions release pipeline** — Automatically builds and publishes the installer on tagged releases
- **App icon** — Custom icon for the exe, taskbar, and installer

### Changed
- **Unified Open action** — Single "Open..." (`Ctrl+O`) replaces separate ROM/Project openers
- **Projects behind feature flag** — Project management UI hidden unless `--enable-projects` is passed

## [v1.2.0] - 2026-02-27

### Added
- **ROM comparison tool** — Side-by-side comparison of two ROMs (`Ctrl+Shift+D`) with change highlighting
- **Cross-definition comparison** — Compare ROMs with different ECU definitions (e.g., NC1 vs NC2)
- **Table viewer toolbar** — 12 quick-access buttons for editing, interpolation, and visualization
- **Main window toolbar** — Open, Save, Compare, Settings buttons with programmatic icons
- **Copy table between ROMs** — Copy table values from one ROM to another in compare view

### Fixed
- **Table viewer auto-sizing** — Fixed last row being clipped behind horizontal scrollbar
- **3D graph performance** — 45% faster initial render, 55% faster selection updates
- **Multi-ROM undo isolation** — Undo stacks no longer shared between ROMs with same definition

## [v1.1.0] - 2026-02-07

### Added
- **Per-table undo/redo** — Each table has its own undo stack
- **Bulk operation performance** — Single repaint for multi-cell operations
- **Min/max coloring from scaling definitions** — Instead of current data values
- **Uniform graph cell sizes** — Non-uniform axis values no longer cause thin edge cells

### Fixed
- **40 code audit findings remediated** — Security (XXE prevention), memory leaks, performance, error handling
- **Atomic file writes** — Prevents ROM corruption on crash
- **Paste uses bulk signal** — Single undo entry instead of N individual entries

## [v1.0.0] - 2026-01-16

### Added
- ROM file reading and writing for NC Miata ECUs
- Automatic ROM ID detection and XML definition matching
- 1D, 2D, and 3D table viewing with axis labels
- Cell editing with validation
- Interactive 3D surface plots and 2D line graphs
- Thermal color gradient with configurable colormaps
- Copy/paste, CSV export, clipboard support
- Interpolation (vertical, horizontal, bilinear) and smoothing
- Multi-ROM tabs with session restore
- Category-based table browser with search
