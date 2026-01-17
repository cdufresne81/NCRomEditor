# Session Notes

## Next Tasks
- **Replace matplotlib with PyQtGraph** in `graph_viewer.py` for better 3D performance
  - PyQtGraph uses OpenGL for hardware acceleration
  - Supports in-place data updates without recreating plots
  - Key issues to solve: full figure recreation, nested Python loops for colors, matplotlib 3D limitations

## Recent Completed Work (Jan 16, 2026)
- Added Copy Table to Clipboard (Ctrl+Shift+C) and Export to CSV (Ctrl+E)
- Added Smooth Selection (S) for light neighbor-based smoothing
- Removed graph widget and "Value" label for 1D tables
- Hidden View menu for 1D tables (when not in diff mode)
- Added graph auto-refresh on data changes
- Fixed undo/redo graph refresh with debouncing (50ms timer)
