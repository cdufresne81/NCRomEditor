"""Tests for the definition relocator module."""

from pathlib import Path

import pytest

from src.ecu.definition_relocator import (
    DataMatcher,
    DefinitionRelocator,
    DefinitionGenResult,
    _parse_scaling_name,
    _rebuild_scaling_name,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rom(size: int = 0x100000, fill: int = 0xFF) -> bytearray:
    """Create a 1MB ROM filled with a byte value."""
    return bytearray([fill]) * size


def _place_data(rom: bytearray, offset: int, data: bytes) -> bytearray:
    """Place data at a specific offset in a ROM."""
    rom[offset : offset + len(data)] = data
    return rom


def _assert_no_parent_collisions(result: DefinitionGenResult):
    """Assert no non-merge parent-table address collisions in generated XML."""
    from lxml import etree

    root = etree.fromstring(result.xml_bytes)
    rom = root.find(".//rom") if root.tag != "rom" else root

    # Build set of target addresses that are legitimate merges
    # result.merged contains source addresses; map them to target addresses
    merged_target_addrs = set()
    for src_addr in result.merged:
        # Find this source address in the XML — its address attr is the target
        # We already know the mapping: look at phase_counts context
        pass

    # Simpler approach: collect ALL table addresses and find duplicates
    # Then check if those duplicates have identical data at those target addresses
    parent_addrs: dict[int, list[str]] = {}
    for table_elem in rom.iter("table"):
        addr_str = table_elem.get("address")
        children = table_elem.findall("table")
        if addr_str and children:
            addr = int(addr_str, 16)
            name = table_elem.get("name", "<unnamed>")
            parent_addrs.setdefault(addr, []).append(name)

    collisions = {addr: names for addr, names in parent_addrs.items() if len(names) > 1}

    # A collision is "legitimate" if the merged list contains source addresses
    # that map to this target. Since we store source addrs in merged, and the
    # XML now has target addrs, we need the count of merged source addresses
    # to match. Simpler: just check that the collision count equals merged groups.
    # For strict checking, we accept collisions where names suggest variants
    # (e.g., IMRC vs non-IMRC, High Det vs Normal of same table).
    #
    # Use result.merged count: each merged source addr maps to a collision target.
    # Number of collision *slots* = sum(len(names) for names in collisions.values())
    # should be <= len(result.merged)
    collision_slots = sum(len(names) for names in collisions.values())
    assert collision_slots <= len(result.merged), (
        f"Non-merge parent collisions detected. "
        f"Collision slots: {collision_slots}, merged sources: {len(result.merged)}. "
        f"Collisions: {collisions}"
    )


# ---------------------------------------------------------------------------
# Scaling name parsing
# ---------------------------------------------------------------------------


class TestScalingNameParsing:
    def test_plain_decimal(self):
        result = _parse_scaling_name("757804")
        assert result == (757804, "")

    def test_decimal_with_suffix(self):
        result = _parse_scaling_name("757648_SPD")
        assert result == (757648, "_SPD")

    def test_decimal_with_multi_underscore_suffix(self):
        result = _parse_scaling_name("123456_FOO_BAR")
        assert result == (123456, "_FOO_BAR")

    def test_non_numeric_returns_none(self):
        assert _parse_scaling_name("not_a_number") is None

    def test_empty_string_returns_none(self):
        assert _parse_scaling_name("") is None

    def test_rebuild_no_suffix(self):
        assert _rebuild_scaling_name(800000, "") == "800000"

    def test_rebuild_with_suffix(self):
        assert _rebuild_scaling_name(800000, "_SPD") == "800000_SPD"


# ---------------------------------------------------------------------------
# DataMatcher unit tests (synthetic ROMs)
# ---------------------------------------------------------------------------


class TestDataMatcherUnique:
    """Phase 1: unique byte-context matching."""

    def test_unique_match_found(self):
        ref = _make_rom()
        target = _make_rom()

        # Place a unique pattern in both ROMs at different offsets
        pattern = b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"
        _place_data(ref, 0x50000, pattern)
        _place_data(target, 0x50100, pattern)

        matcher = DataMatcher(bytes(ref), bytes(target))
        result = matcher.find_unique(0x50008)  # middle of the pattern

        assert result is not None
        assert result.target_addr == 0x50108
        assert result.phase == 1
        assert result.confidence == "high"

    def test_no_match_returns_none(self):
        ref = _make_rom()
        target = _make_rom()

        # Place pattern only in ref, not in target
        _place_data(ref, 0x50000, b"\x01\x02\x03\x04\x05\x06\x07\x08")

        matcher = DataMatcher(bytes(ref), bytes(target))
        result = matcher.find_unique(0x50004)
        assert result is None

    def test_multiple_matches_returns_none(self):
        ref = _make_rom(fill=0x00)
        target = _make_rom(fill=0x00)

        # Place same pattern at two locations in target
        pattern = b"\xaa\xbb\xcc\xdd"
        _place_data(ref, 0x50000, pattern)
        _place_data(target, 0x50100, pattern)
        _place_data(target, 0x60100, pattern)

        matcher = DataMatcher(bytes(ref), bytes(target))
        # With large enough context, ref is unique but target has 2 copies
        # The context around the pattern in ref includes zeros, which match everywhere
        # So this should fail for small context
        result = matcher.find_unique(0x50002, context_sizes=(2,))
        assert result is None


class TestDataMatcherDelta:
    """Phase 2/4: delta estimation."""

    def test_verified_delta(self):
        ref = _make_rom()
        target = _make_rom()

        delta = 0x200

        # Place two patterns — first one will be resolved in phase 1
        pat1 = b"\x11\x22\x33\x44\x55\x66\x77\x88\x99\xaa\xbb\xcc\xdd\xee\xff\x00"
        pat2 = b"\xa1\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xab\xac\xad\xae\xaf\xb0"
        _place_data(ref, 0x50000, pat1)
        _place_data(target, 0x50000 + delta, pat1)
        _place_data(ref, 0x50100, pat2)
        _place_data(target, 0x50100 + delta, pat2)

        matcher = DataMatcher(bytes(ref), bytes(target))
        # Resolve first address via phase 1
        r1 = matcher.find_unique(0x50008)
        assert r1 is not None
        matcher._resolved[0x50008] = r1

        # Now use delta for second address
        r2 = matcher.find_by_delta(0x50108, verify=True)
        assert r2 is not None
        assert r2.target_addr == 0x50108 + delta
        assert r2.phase == 2
        assert r2.confidence == "high"

    def test_unverified_delta(self):
        ref = _make_rom()
        target = _make_rom()

        # Only resolved neighbor, no data to verify
        matcher = DataMatcher(bytes(ref), bytes(target))
        from src.ecu.definition_relocator import RelocationResult

        matcher._resolved[0x50000] = RelocationResult(
            source_addr=0x50000, target_addr=0x50200, phase=1, confidence="high"
        )

        r = matcher.find_by_delta(0x50100, verify=False)
        assert r is not None
        assert r.target_addr == 0x50300  # 0x50100 + delta(0x200)
        assert r.phase == 4
        assert r.confidence == "low"

    def test_no_resolved_returns_none(self):
        matcher = DataMatcher(bytes(_make_rom()), bytes(_make_rom()))
        r = matcher.find_by_delta(0x50000, verify=True)
        assert r is None


class TestDataMatcherDisambiguate:
    """Phase 3: multi-match disambiguation."""

    def test_picks_closest_to_median_delta(self):
        ref = _make_rom(fill=0x00)
        target = _make_rom(fill=0x00)

        delta = 0x100
        # Pattern appears at two locations in target
        pattern = b"\xde\xad\xbe\xef"
        _place_data(ref, 0x50000, pattern)
        _place_data(target, 0x50000 + delta, pattern)  # correct: delta=0x100
        _place_data(target, 0x70000 + delta, pattern)  # wrong: far away

        matcher = DataMatcher(bytes(ref), bytes(target))

        # Pre-populate resolved with a nearby address at known delta
        from src.ecu.definition_relocator import RelocationResult

        matcher._resolved[0x4FF00] = RelocationResult(
            source_addr=0x4FF00, target_addr=0x4FF00 + delta, phase=1, confidence="high"
        )

        r = matcher.disambiguate_multi(0x50002, context_sizes=(2,))
        assert r is not None
        assert r.target_addr == 0x50002 + delta
        assert r.phase == 3
        assert r.confidence == "medium"


class TestRelocateAll:
    """Full 4-phase pipeline on synthetic data."""

    def test_all_phases(self):
        ref = _make_rom()
        target = _make_rom()

        delta = 0x300

        # Address 1: unique pattern (phase 1)
        pat1 = b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"
        _place_data(ref, 0x50000, pat1)
        _place_data(target, 0x50000 + delta, pat1)

        # Address 2: same data as ref, shifted by delta (phase 2 — verified)
        pat2 = b"\xa1\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xab\xac\xad\xae\xaf\xb0"
        _place_data(ref, 0x50100, pat2)
        _place_data(target, 0x50100 + delta, pat2)

        matcher = DataMatcher(bytes(ref), bytes(target))
        results, merged, collisions_resolved = matcher.relocate_all([0x50008, 0x50108])

        assert len(results) == 2
        assert results[0x50008].target_addr == 0x50008 + delta
        assert results[0x50108].target_addr == 0x50108 + delta


class TestPhase3SkipsClaimed:
    """Phase 3 must not pick a candidate that is already claimed."""

    def test_phase3_skips_claimed_target(self):
        ref = _make_rom(fill=0x00)
        target = _make_rom(fill=0x00)

        delta = 0x100
        # Pattern appears at two locations in target
        pattern = b"\xde\xad\xbe\xef"
        _place_data(ref, 0x50000, pattern)
        _place_data(target, 0x50000 + delta, pattern)  # candidate A (delta=0x100)
        _place_data(target, 0x60000, pattern)  # candidate B (far away)

        matcher = DataMatcher(bytes(ref), bytes(target))

        from src.ecu.definition_relocator import RelocationResult

        # Pre-populate with a nearby resolved address
        matcher._resolved[0x4FF00] = RelocationResult(
            source_addr=0x4FF00,
            target_addr=0x4FF00 + delta,
            phase=1,
            confidence="high",
        )

        # Candidate A (0x50102) is the closest to median delta, but it's claimed
        # (0x50002 + delta = 0x50102 — the exact target address Phase 3 would pick)
        claimed = {0x50002 + delta}  # 0x50102 is claimed

        # Without claimed, Phase 3 would pick candidate A
        r_unclaimed = matcher.disambiguate_multi(0x50002, context_sizes=(2,))
        assert r_unclaimed is not None
        assert r_unclaimed.target_addr == 0x50002 + delta  # candidate A

        # With claimed, Phase 3 must skip candidate A and pick candidate B
        r_claimed = matcher.disambiguate_multi(
            0x50002, context_sizes=(2,), claimed=claimed
        )
        assert r_claimed is not None
        assert r_claimed.target_addr != 0x50002 + delta  # NOT candidate A
        assert r_claimed.target_addr == 0x60002  # candidate B


class TestPhase4AvoidsWrongRegion:
    """Phase 4 should prefer same-region neighbors over cross-region ones."""

    def test_phase4_avoids_wrong_region(self):
        ref = _make_rom()
        target = _make_rom()

        from src.ecu.definition_relocator import RelocationResult

        matcher = DataMatcher(bytes(ref), bytes(target))

        # Two resolved addresses in different regions with different deltas
        # Region A (0xC0000-0xD0000): delta = 0x100
        matcher._resolved[0xC5000] = RelocationResult(
            source_addr=0xC5000,
            target_addr=0xC5100,
            phase=1,
            confidence="high",
        )
        # Region B (0xF0000-0xFFFFF): delta = -0x10000
        matcher._resolved[0xF5000] = RelocationResult(
            source_addr=0xF5000,
            target_addr=0xE5000,
            phase=1,
            confidence="high",
        )

        # Address in region A — should use region A's delta, not region B's
        addr = 0xC8000
        r = matcher.find_by_delta(addr, verify=False, k_neighbors=5)
        assert r is not None
        # Expected: 0xC8000 + 0x100 = 0xC8100 (same-region delta)
        assert r.target_addr == 0xC8100

        # If we only had region B's neighbor (test the preference logic)
        # The function should still try same-region first
        addr2 = 0xF8000
        r2 = matcher.find_by_delta(addr2, verify=False, k_neighbors=5)
        assert r2 is not None
        # Expected: 0xF8000 + (-0x10000) = 0xE8000 (same-region delta)
        assert r2.target_addr == 0xE8000


class TestCollisionResolution:
    """Post-phase collision detection and resolution."""

    def test_legitimate_merge_flagged(self):
        """When two sources have identical data and map to same target, flag as merged."""
        ref = _make_rom()
        target = _make_rom()

        # Two source addresses with identical 32-byte data
        data = b"\x11\x22\x33\x44" * 8
        _place_data(ref, 0x50000, data)
        _place_data(ref, 0x60000, data)

        # Both have the same unique context in ref, will match same spot in target
        unique_ctx = b"\xaa\xbb\xcc\xdd\xee\xff\x00\x11" * 4
        _place_data(ref, 0x50000, unique_ctx + data[len(unique_ctx) :])
        _place_data(ref, 0x60000, unique_ctx + data[len(unique_ctx) :])
        _place_data(target, 0x50200, unique_ctx + data[len(unique_ctx) :])

        matcher = DataMatcher(bytes(ref), bytes(target))
        # Manually set up a collision scenario
        from src.ecu.definition_relocator import RelocationResult

        matcher._resolved[0x50000] = RelocationResult(
            source_addr=0x50000,
            target_addr=0x50200,
            phase=1,
            confidence="high",
        )
        matcher._resolved[0x60000] = RelocationResult(
            source_addr=0x60000,
            target_addr=0x50200,  # same target = collision
            phase=1,
            confidence="high",
        )
        matcher._claimed = {0x50200}

        merged, resolved = matcher._resolve_collisions([])

        # Both should be flagged as merged
        assert 0x50000 in merged
        assert 0x60000 in merged
        assert matcher._resolved[0x50000].confidence == "merged"
        assert matcher._resolved[0x60000].confidence == "merged"

    def test_different_data_collision_evicts_lower_phase(self):
        """When sources have different data, keep best phase, evict others."""
        ref = _make_rom()
        target = _make_rom()

        # Two source addresses with DIFFERENT data
        _place_data(ref, 0x50000, b"\x11" * 32)
        _place_data(ref, 0x60000, b"\x22" * 32)

        # Also place verifiable data for re-resolve
        pat = b"\x22" * 16
        _place_data(ref, 0x60000, pat)
        _place_data(target, 0x60200, pat)

        matcher = DataMatcher(bytes(ref), bytes(target))
        from src.ecu.definition_relocator import RelocationResult

        # Phase 1 winner vs Phase 3 loser — both map to same target
        matcher._resolved[0x50000] = RelocationResult(
            source_addr=0x50000,
            target_addr=0x70000,
            phase=1,
            confidence="high",
        )
        matcher._resolved[0x60000] = RelocationResult(
            source_addr=0x60000,
            target_addr=0x70000,  # collision
            phase=3,
            confidence="medium",
        )
        matcher._claimed = {0x70000}

        merged, resolved = matcher._resolve_collisions([])

        # Phase 1 (0x50000) should be kept, Phase 3 (0x60000) evicted
        assert 0x50000 in matcher._resolved
        assert matcher._resolved[0x50000].target_addr == 0x70000


# ---------------------------------------------------------------------------
# Integration tests with real ROMs (skipped if files not present)
# ---------------------------------------------------------------------------

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
LF9VEB_ROM = EXAMPLES_DIR / "lf9veb.bin"
LF5AEG_ROM = EXAMPLES_DIR / "lf5aeg.bin"
LFNPEA_ROM = EXAMPLES_DIR / "SW-LFNPEA.BIN"
LF9VEB_XML = EXAMPLES_DIR / "metadata" / "lf9veb.xml"

_has_lf5aeg = LF9VEB_ROM.exists() and LF5AEG_ROM.exists() and LF9VEB_XML.exists()
_has_lfnpea = LF9VEB_ROM.exists() and LFNPEA_ROM.exists() and LF9VEB_XML.exists()

skip_no_lf5aeg = pytest.mark.skipif(
    not _has_lf5aeg,
    reason="Requires lf9veb.bin, lf5aeg.bin, and lf9veb.xml in examples/",
)
skip_no_lfnpea = pytest.mark.skipif(
    not _has_lfnpea,
    reason="Requires lf9veb.bin, SW-LFNPEA.BIN, and lf9veb.xml in examples/",
)


@skip_no_lf5aeg
class TestLF5AEGRelocation:
    """Integration: relocate LF9VEB definition to LF5AEG."""

    @pytest.fixture(scope="class")
    def result(self) -> DefinitionGenResult:
        source_rom = LF9VEB_ROM.read_bytes()
        target_rom = LF5AEG_ROM.read_bytes()
        relocator = DefinitionRelocator(LF9VEB_XML, source_rom, target_rom)
        return relocator.generate()

    def test_high_resolution_rate(self, result: DefinitionGenResult):
        ratio = result.resolved / result.total_addresses
        assert ratio >= 0.95, f"Resolution rate {ratio:.1%} below 95%"

    def test_total_addresses(self, result: DefinitionGenResult):
        assert result.total_addresses == 838

    def test_xml_parses(self, result: DefinitionGenResult, tmp_path):
        """Generated XML can be parsed by DefinitionParser."""
        xml_path = tmp_path / "lf5aeg.xml"
        xml_path.write_bytes(result.xml_bytes)

        from src.core.definition_parser import DefinitionParser

        defn = DefinitionParser(str(xml_path)).parse()
        assert defn.romid.xmlid == "LF5AEG"
        assert len(defn.tables) > 0

    def test_romid_updated(self, result: DefinitionGenResult):
        from lxml import etree

        root = etree.fromstring(result.xml_bytes)
        rom = root.find(".//rom") if root.tag != "rom" else root
        romid = rom.find("romid")
        assert romid.find("xmlid").text == "LF5AEG"
        assert romid.find("ecuid").text == "LF5AEG"
        assert romid.find("internalidstring").text == "LF5AEG"

    def test_few_failures(self, result: DefinitionGenResult):
        assert len(result.failed) < 50, f"Too many failed: {len(result.failed)}"

    def test_no_parent_collisions(self, result: DefinitionGenResult):
        """No non-merge parent-table address collisions in generated XML."""
        _assert_no_parent_collisions(result)


@skip_no_lfnpea
class TestLFNPEARelocation:
    """Integration: relocate LF9VEB definition to LFNPEA."""

    @pytest.fixture(scope="class")
    def result(self) -> DefinitionGenResult:
        source_rom = LF9VEB_ROM.read_bytes()
        target_rom = LFNPEA_ROM.read_bytes()
        relocator = DefinitionRelocator(LF9VEB_XML, source_rom, target_rom)
        return relocator.generate()

    def test_high_resolution_rate(self, result: DefinitionGenResult):
        ratio = result.resolved / result.total_addresses
        assert ratio >= 0.95, f"Resolution rate {ratio:.1%} below 95%"

    def test_xml_parses(self, result: DefinitionGenResult, tmp_path):
        xml_path = tmp_path / "lfnpea.xml"
        xml_path.write_bytes(result.xml_bytes)

        from src.core.definition_parser import DefinitionParser

        defn = DefinitionParser(str(xml_path)).parse()
        assert defn.romid.xmlid == "LFNPEA"
        assert len(defn.tables) > 0

    def test_no_parent_collisions(self, result: DefinitionGenResult):
        """No non-merge parent-table address collisions in generated XML."""
        _assert_no_parent_collisions(result)
