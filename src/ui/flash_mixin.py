"""
Flash Mixin for MainWindow

Provides the Patch ROM dialog action.

This is a mixin class — it has no __init__. It relies on MainWindow being a
QWidget (used as the dialog parent) and providing:
- self._open_rom_file(path) method

Note: the ECU *session* is owned solely by ECUProgrammingWindow (src/ui/ecu_window.py).
This mixin used to carry a parallel `_ecu_session` half that was never wired up
(it stayed None forever) yet ecu_window read it as if it were live; that dead
half was removed (audit C6). Do not reintroduce a MainWindow-owned ECU session.
"""


class FlashMixin:
    """Mixin providing the Patch ROM action for MainWindow."""

    def _on_patch_rom(self):
        """Apply an XOR patch to a stock ROM via the Patch ROM dialog."""
        from src.ui.patch_dialog import PatchRomDialog

        dlg = PatchRomDialog(parent=self)
        dlg.exec()

        # The dialog asks the user whether to open the patched ROM; opening it
        # is MainWindow's job, so the dialog only reports the answer back.
        if dlg.open_requested and dlg.patched_rom_path:
            self._open_rom_file(dlg.patched_rom_path)
