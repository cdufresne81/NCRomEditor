"""Tests for src/ecu/sh2_match.py and src/ecu/patch_generator.py."""

from pathlib import Path

import pytest
from src.ecu.sh2_match import (
    mask_sh2_instructions,
    find_pattern,
    find_referencing_movl,
    SH2Matcher,
)
from src.ecu.patch_generator import (
    extract_mod_sites,
    classify_hook,
    _apply_patch_xor,
    HookSite,
    HookType,
    generate_patch,
)
from src.ecu.constants import ROM_SIZE
from src.ecu.rom_utils import get_cal_id, detect_vehicle_generation

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"

STOCK_5AEG = EXAMPLES_DIR / "lf5aeg.bin"
PATCH_5AEG = EXAMPLES_DIR / "lf5aeg.patch"
STOCK_9VEB = EXAMPLES_DIR / "lf9veb.bin"
PATCH_9VEB = EXAMPLES_DIR / "lf9veb.patch"
TARGET_LFNPEA = EXAMPLES_DIR / "SW-LFNPEA.BIN"

_has_5aeg = STOCK_5AEG.exists() and PATCH_5AEG.exists()
_has_9veb = STOCK_9VEB.exists() and PATCH_9VEB.exists()
_has_both = _has_5aeg and _has_9veb
_has_lfnpea = TARGET_LFNPEA.exists()

_skip_no_5aeg = pytest.mark.skipif(not _has_5aeg, reason="Requires LF5AEG files")
_skip_no_9veb = pytest.mark.skipif(not _has_9veb, reason="Requires LF9VEB files")
_skip_no_both = pytest.mark.skipif(
    not _has_both, reason="Requires both LF5AEG and LF9VEB"
)
_skip_no_lfnpea = pytest.mark.skipif(
    not (_has_both and _has_lfnpea), reason="Requires LF5AEG, LF9VEB, and SW-LFNPEA.BIN"
)


# =========================================================================
# SH-2 Instruction Masking
# =========================================================================


class TestMaskSH2Instructions:
    """Test mask_sh2_instructions()."""

    def test_nop_unchanged(self):
        """NOP (0x0009) is not masked."""
        data = bytes([0x00, 0x09])
        assert mask_sh2_instructions(data) == data

    def test_mov_w_pc_masked(self):
        """MOV.W @(disp,PC),Rn (0x9nXX) masks displacement."""
        data = bytes([0x93, 0x42])  # MOV.W @(0x42*2+PC+4),R3
        result = mask_sh2_instructions(data)
        assert result == bytes([0x93, 0x00])

    def test_mov_l_pc_masked(self):
        """MOV.L @(disp,PC),Rn (0xDnXX) masks displacement."""
        data = bytes([0xD5, 0x1A])  # MOV.L @(0x1A*4+PC+4),R5
        result = mask_sh2_instructions(data)
        assert result == bytes([0xD5, 0x00])

    def test_bra_masked(self):
        """BRA (0xAnXX) masks all 12 displacement bits."""
        data = bytes([0xAF, 0x42])
        result = mask_sh2_instructions(data)
        assert result == bytes([0xA0, 0x00])

    def test_bsr_masked(self):
        """BSR (0xBnXX) masks all 12 displacement bits."""
        data = bytes([0xB3, 0x80])
        result = mask_sh2_instructions(data)
        assert result == bytes([0xB0, 0x00])

    def test_bt_bf_masked(self):
        """BT/BF/BT.S/BF.S conditional branches mask displacement."""
        for hi_byte in [0x89, 0x8B, 0x8D, 0x8F]:
            data = bytes([hi_byte, 0x55])
            result = mask_sh2_instructions(data)
            assert result == bytes([hi_byte, 0x00])

    def test_register_op_unchanged(self):
        """Register-register operations are not masked."""
        # ADD Rm,Rn (0x3nmC) — no displacement
        data = bytes([0x34, 0x8C])
        assert mask_sh2_instructions(data) == data

    def test_jsr_unchanged(self):
        """JSR @Rn (0x4n0B) is not masked."""
        data = bytes([0x4B, 0x0B])  # JSR @R11
        assert mask_sh2_instructions(data) == data

    def test_multiple_instructions(self):
        """Multiple instructions are masked independently."""
        # MOV.L + NOP + BRA
        data = bytes([0xD1, 0x07, 0x00, 0x09, 0xA5, 0x42])
        result = mask_sh2_instructions(data)
        assert result == bytes([0xD1, 0x00, 0x00, 0x09, 0xA0, 0x00])

    def test_odd_length_truncated(self):
        """Odd-length data is truncated to even length."""
        data = bytes([0xD1, 0x07, 0x00])
        result = mask_sh2_instructions(data)
        assert result == bytes([0xD1, 0x00])

    def test_empty_input(self):
        """Empty input returns empty output."""
        assert mask_sh2_instructions(b"") == b""


class TestFindPattern:
    """Test find_pattern()."""

    def test_single_match(self):
        """Single occurrence found."""
        haystack = b"\x00\x01\x02\x03\x04"
        assert find_pattern(haystack, b"\x02\x03") == [2]

    def test_multiple_matches(self):
        """Multiple occurrences found."""
        haystack = b"\xaa\xbb\xaa\xbb\xaa"
        assert find_pattern(haystack, b"\xaa\xbb") == [0, 2]

    def test_no_match(self):
        """No match returns empty list."""
        haystack = b"\x00\x01\x02"
        assert find_pattern(haystack, b"\xff") == []

    def test_with_start_offset(self):
        """Start offset skips earlier occurrences."""
        haystack = b"\xaa\xbb\xaa\xbb"
        assert find_pattern(haystack, b"\xaa\xbb", start=1) == [2]


class TestFindReferencingMovl:
    """Test find_referencing_movl()."""

    def test_finds_movl(self):
        """Finds MOV.L instruction referencing a pool entry."""
        # Create ROM with MOV.L @(disp,PC),R2 at address 0x2100
        # Pool entry at 0x2110: (0x2100 & ~3) + 4 + disp*4 = 0x2104 + disp*4
        # Want pool at 0x2110: disp = (0x2110 - 0x2104) / 4 = 3
        rom = bytearray(ROM_SIZE)
        rom[0x2100] = 0xD2  # MOV.L ..., R2
        rom[0x2101] = 0x03  # disp = 3
        assert find_referencing_movl(bytes(rom), 0x2110) == 0x2100

    def test_no_movl_returns_none(self):
        """No MOV.L referencing the address returns None."""
        rom = bytes(ROM_SIZE)
        assert find_referencing_movl(rom, 0x5000) is None


# =========================================================================
# SH2Matcher (integration with real ROMs)
# =========================================================================


class TestSH2Matcher:
    """Integration tests for SH2Matcher with real ROM files."""

    @_skip_no_both
    def test_find_known_jsr_hook(self):
        """Known JSR hook (0x043C76 in LF5AEG) found in LF9VEB."""
        stock_5 = STOCK_5AEG.read_bytes()
        stock_9 = STOCK_9VEB.read_bytes()
        matcher = SH2Matcher(stock_5, stock_9)

        # LF5AEG JSR at 0x043C76 -> LF9VEB JSR at 0x04470E
        result = matcher.find_address(0x043C76)
        assert result == 0x04470E

    @_skip_no_both
    def test_find_code_replacement(self):
        """Known code replacement (0x032F52 in LF5AEG) found in LF9VEB."""
        stock_5 = STOCK_5AEG.read_bytes()
        stock_9 = STOCK_9VEB.read_bytes()
        matcher = SH2Matcher(stock_5, stock_9)

        result = matcher.find_address(0x032F52)
        assert result == 0x033782

    @_skip_no_both
    def test_find_majority_of_hooks(self):
        """At least 70% of hooks are found with a single reference."""
        stock_5 = STOCK_5AEG.read_bytes()
        patch_5 = PATCH_5AEG.read_bytes()
        stock_9 = STOCK_9VEB.read_bytes()

        patched = _apply_patch_xor(stock_5, patch_5)
        sites = extract_mod_sites(stock_5, patched)
        hooks = [s for s in sites if not s.is_ff]

        matcher = SH2Matcher(stock_5, stock_9)
        found = sum(
            1
            for h in hooks
            if matcher.find_address(h.addr, is_pool_entry=h.hook_type == HookType.POOL)
            is not None
        )
        assert found / len(hooks) >= 0.70, f"Only {found}/{len(hooks)} hooks found"


# =========================================================================
# Mod Site Extraction and Classification
# =========================================================================


class TestExtractModSites:
    """Test extract_mod_sites() and classify_hook()."""

    @_skip_no_5aeg
    def test_site_count(self):
        """LF5AEG has ~170 modification sites."""
        stock = STOCK_5AEG.read_bytes()
        patch = PATCH_5AEG.read_bytes()
        patched = _apply_patch_xor(stock, patch)
        sites = extract_mod_sites(stock, patched)
        assert 160 <= len(sites) <= 180

    @_skip_no_5aeg
    def test_hook_classification(self):
        """All hook types are represented."""
        stock = STOCK_5AEG.read_bytes()
        patch = PATCH_5AEG.read_bytes()
        patched = _apply_patch_xor(stock, patch)
        sites = extract_mod_sites(stock, patched)

        types = {s.hook_type for s in sites}
        assert HookType.PAYLOAD in types
        assert HookType.HANDLER in types
        assert HookType.JSR in types
        assert HookType.POOL in types

    @_skip_no_5aeg
    def test_jsr_hooks_all_target_r4(self):
        """All JSR hooks change to register R4 (0x44)."""
        stock = STOCK_5AEG.read_bytes()
        patch = PATCH_5AEG.read_bytes()
        patched = _apply_patch_xor(stock, patch)
        sites = extract_mod_sites(stock, patched)
        jsr_hooks = [s for s in sites if s.hook_type == HookType.JSR]

        assert len(jsr_hooks) > 0
        for h in jsr_hooks:
            assert h.size == 1
            assert h.patched_bytes[0] == 0x44

    @_skip_no_5aeg
    def test_pool_redirects_point_to_handler_region(self):
        """Pool redirect patched bytes start with 0x0F (handler region)."""
        stock = STOCK_5AEG.read_bytes()
        patch = PATCH_5AEG.read_bytes()
        patched = _apply_patch_xor(stock, patch)
        sites = extract_mod_sites(stock, patched)
        pool_hooks = [s for s in sites if s.hook_type == HookType.POOL]

        assert len(pool_hooks) > 0
        for h in pool_hooks:
            assert h.size == 3
            assert h.patched_bytes[0] == 0x0F

    @_skip_no_5aeg
    def test_flash_counter_excluded(self):
        """Flash counter region (0xFFB00-0xFFB08) is not extracted as a hook."""
        stock = STOCK_5AEG.read_bytes()
        patch = PATCH_5AEG.read_bytes()
        patched = _apply_patch_xor(stock, patch)
        sites = extract_mod_sites(stock, patched)

        for s in sites:
            assert not (
                0xFFB00 <= s.addr < 0xFFB08
            ), f"Flash counter hook at 0x{s.addr:06X} should be filtered"

    @_skip_no_both
    def test_consistent_hook_counts(self):
        """LF5AEG and LF9VEB have similar hook counts."""
        for stock_p, patch_p in [
            (STOCK_5AEG, PATCH_5AEG),
            (STOCK_9VEB, PATCH_9VEB),
        ]:
            stock = stock_p.read_bytes()
            patch = patch_p.read_bytes()
            patched = _apply_patch_xor(stock, patch)
            sites = extract_mod_sites(stock, patched)
            hooks = [s for s in sites if not s.is_ff]
            # Both should have ~75-80 hooks
            assert 70 <= len(hooks) <= 90, f"{stock_p.name}: {len(hooks)} hooks"


# =========================================================================
# Classify hook edge cases
# =========================================================================


class TestClassifyHook:
    """Test classify_hook() with synthetic data."""

    def test_jsr_register_change(self):
        """Single byte 0x4X -> 0x44 classified as JSR."""
        site = HookSite(
            addr=0x40000,
            size=1,
            stock_bytes=bytes([0x4B]),
            patched_bytes=bytes([0x44]),
            is_ff=False,
        )
        classify_hook(site)
        assert site.hook_type == HookType.JSR

    def test_pool_redirect(self):
        """3-byte redirect to 0x0F???? classified as POOL."""
        site = HookSite(
            addr=0x30000,
            size=3,
            stock_bytes=b"\x04\x51\xba",
            patched_bytes=b"\x0f\xbc\xd0",
            is_ff=False,
        )
        classify_hook(site)
        assert site.hook_type == HookType.POOL

    def test_ff_high_address_is_handler(self):
        """0xFF-region at high address classified as HANDLER."""
        site = HookSite(
            addr=0x0FC000,
            size=36,
            stock_bytes=b"\xff" * 36,
            patched_bytes=b"\x00" * 36,
            is_ff=True,
        )
        classify_hook(site)
        assert site.hook_type == HookType.HANDLER

    def test_ff_low_address_is_payload(self):
        """0xFF-region at low address classified as PAYLOAD."""
        site = HookSite(
            addr=0x0F0000,
            size=1000,
            stock_bytes=b"\xff" * 1000,
            patched_bytes=b"\x00" * 1000,
            is_ff=True,
        )
        classify_hook(site)
        assert site.hook_type == HookType.PAYLOAD

    def test_data_high_address(self):
        """Small change at high data address classified as DATA."""
        site = HookSite(
            addr=0x090000,
            size=1,
            stock_bytes=bytes([0x00]),
            patched_bytes=bytes([0x10]),
            is_ff=False,
        )
        classify_hook(site)
        assert site.hook_type == HookType.DATA

    def test_code_replacement(self):
        """Larger modification in code area classified as CODE."""
        site = HookSite(
            addr=0x040000,
            size=10,
            stock_bytes=b"\x00" * 10,
            patched_bytes=b"\x01" * 10,
            is_ff=False,
        )
        classify_hook(site)
        assert site.hook_type == HookType.CODE


# =========================================================================
# Round-trip / golden-file test
# =========================================================================


class TestGeneratePatchRoundTrip:
    """
    Round-trip test: generate a patch for a KNOWN calibration from the
    OTHER reference, then compare against the original patch.

    This is the gold standard: if we can reproduce a known patch,
    the algorithm works for unknown calibrations too.
    """

    @_skip_no_both
    def test_generate_for_lf9veb_using_lf5aeg(self):
        """Generate LF9VEB patch using LF5AEG as sole reference.

        This tests the core matching pipeline with a single reference.
        We check that the majority of hooks are found (not byte-for-byte
        identity with the original patch, since embedded addresses in the
        payload region need 2+ references to fix).
        """
        target = STOCK_9VEB.read_bytes()
        patch_9 = PATCH_9VEB.read_bytes()

        # Create temp dirs with just the LF5AEG reference
        import tempfile, shutil

        with tempfile.TemporaryDirectory() as tmpdir:
            refs = Path(tmpdir) / "refs"
            patches = Path(tmpdir) / "patches"
            refs.mkdir()
            patches.mkdir()
            shutil.copy(STOCK_5AEG, refs / "lf5aeg.bin")
            shutil.copy(PATCH_5AEG, patches / "lf5aeg.patch")

            result = generate_patch(target, refs, patches)

        assert result.target_cal_id == b"LF9VEB"
        # With single reference, we expect ~70%+ hook finding
        assert result.hooks_found / result.hooks_total >= 0.70
        # 0xFF region should be copied
        assert result.ff_bytes_copied > 20000
        # Patch should be 1MB
        assert len(result.patch_data) == ROM_SIZE
        # First byte should be 'L' (cal-ID header)
        assert result.patch_data[0:1] == b"L"

    @_skip_no_both
    def test_generate_with_both_references(self):
        """Generate LF9VEB patch using both LF5AEG and LF9VEB as references.

        With 2 references we can fix embedded addresses.
        When using the target's own patch as a reference, we should get
        perfect results.
        """
        target = STOCK_9VEB.read_bytes()

        import tempfile, shutil

        with tempfile.TemporaryDirectory() as tmpdir:
            refs = Path(tmpdir) / "refs"
            patches = Path(tmpdir) / "patches"
            refs.mkdir()
            patches.mkdir()
            shutil.copy(STOCK_5AEG, refs / "lf5aeg.bin")
            shutil.copy(PATCH_5AEG, patches / "lf5aeg.patch")
            shutil.copy(STOCK_9VEB, refs / "lf9veb.bin")
            shutil.copy(PATCH_9VEB, patches / "lf9veb.patch")

            result = generate_patch(target, refs, patches)

        assert result.target_cal_id == b"LF9VEB"
        # With the target's own reference included, 100% hooks found
        assert result.hooks_found == result.hooks_total


# =========================================================================
# LFNPEA generation test (new calibration with no existing patch)
# =========================================================================


class TestGeneratePatchLFNPEA:
    """Test generating a patch for LFNPEA (no existing patch)."""

    @_skip_no_lfnpea
    def test_lfnpea_generation(self):
        """Generate LFNPEA patch and verify basic properties."""
        target = TARGET_LFNPEA.read_bytes()

        import tempfile, shutil

        with tempfile.TemporaryDirectory() as tmpdir:
            refs = Path(tmpdir) / "refs"
            patches = Path(tmpdir) / "patches"
            refs.mkdir()
            patches.mkdir()
            shutil.copy(STOCK_5AEG, refs / "lf5aeg.bin")
            shutil.copy(PATCH_5AEG, patches / "lf5aeg.patch")
            shutil.copy(STOCK_9VEB, refs / "lf9veb.bin")
            shutil.copy(PATCH_9VEB, patches / "lf9veb.patch")

            result = generate_patch(target, refs, patches)

        cal_id = result.target_cal_id.decode("ascii", errors="replace")
        assert cal_id.startswith("LFNPEA")

        # LFNPEA is NC2, same as LF5AEG/LF9VEB
        gen = detect_vehicle_generation(target)
        assert gen == "NC2"

        # Should find majority of hooks
        assert result.hooks_found > 0
        assert result.hooks_found / result.hooks_total >= 0.50  # Conservative

        # 0xFF region injections should land in free space
        # LFNPEA may have less free space than LF5AEG/LF9VEB
        assert result.ff_bytes_copied > 15000

        # Patch file basics
        assert len(result.patch_data) == ROM_SIZE
        assert result.patch_data[0:1] == b"L"

        # Verify ROM ID written
        from src.ecu.constants import ROM_ID_OFFSET

        # The XOR mask should be non-zero at ROM_ID_OFFSET (writing the ROM ID)
        rom_id_mask = result.patch_data[ROM_ID_OFFSET : ROM_ID_OFFSET + 4]
        assert rom_id_mask != b"\x00\x00\x00\x00"

    @_skip_no_lfnpea
    def test_lfnpea_ff_regions_are_free(self):
        """Target ROM has 0xFF at all payload/handler addresses."""
        target = TARGET_LFNPEA.read_bytes()

        # Check the handler stub region (>= 0x0FC000, where most stubs live)
        handler_region = target[0x0FC000:0x0FF000]
        non_ff = sum(1 for b in handler_region if b != 0xFF)
        # This inner region should be mostly free (checksum table etc. is above 0xFF000)
        assert non_ff < 500, f"Handler region has {non_ff} non-0xFF bytes"
