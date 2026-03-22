"""
XML definition relocator for cross-calibration ROM definitions.

Given a source XML definition + source ROM + target ROM, generates a new XML
definition with all table addresses relocated. Uses raw byte-context matching
(no SH-2 instruction masking — table data is calibration data, not code).

4-phase relocation algorithm:
  Phase 1 — Unique byte-context match (expanding window 8→256 bytes)
  Phase 2 — Delta estimation from nearest resolved neighbor + verification
  Phase 3 — Multi-match disambiguation using local delta median
  Phase 4 — Unverified delta estimation (flagged low-confidence)
"""

import logging
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .rom_utils import get_cal_id, validate_rom_size
from .constants import CAL_ID_OFFSETS
from .sh2_match import find_pattern

logger = logging.getLogger(__name__)


@dataclass
class RelocationResult:
    """Result of relocating a single address."""

    source_addr: int
    target_addr: int | None
    phase: int  # 1-4
    confidence: str  # "high", "medium", "low"
    context_size: int = 0  # context window that produced the match


@dataclass
class DefinitionGenResult:
    """Result of generating a relocated XML definition."""

    xml_bytes: bytes
    total_addresses: int
    resolved: int
    phase_counts: dict[int, int] = field(default_factory=dict)
    low_confidence: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    merged: list[int] = field(default_factory=list)
    collisions_resolved: int = 0


class DataMatcher:
    """
    Raw byte-context matcher for calibration data relocation.

    Simpler than SH2Matcher — no instruction masking needed since table data
    is floats/ints, not code. Reuses find_pattern() for byte searching.
    """

    _DEFAULT_CONTEXT_SIZES = (8, 16, 32, 64, 128, 256)

    def __init__(self, ref_rom: bytes, target_rom: bytes):
        self.ref_rom = ref_rom
        self.target_rom = target_rom
        self._resolved: dict[int, RelocationResult] = {}

    def find_unique(
        self,
        addr: int,
        context_sizes: tuple[int, ...] | None = None,
    ) -> RelocationResult | None:
        """
        Phase 1: Find addr in target using expanding byte-context windows.

        Returns result only if exactly one match is found (unique).
        """
        if context_sizes is None:
            context_sizes = self._DEFAULT_CONTEXT_SIZES

        for ctx_size in context_sizes:
            ctx_start = max(0, addr - ctx_size)
            ctx_end = min(len(self.ref_rom), addr + ctx_size)
            context = self.ref_rom[ctx_start:ctx_end]

            if len(context) < 4:
                continue

            matches = find_pattern(self.target_rom, context)

            if len(matches) == 1:
                offset_in_ctx = addr - ctx_start
                target_addr = matches[0] + offset_in_ctx
                return RelocationResult(
                    source_addr=addr,
                    target_addr=target_addr,
                    phase=1,
                    confidence="high",
                    context_size=ctx_size,
                )

        return None

    def find_by_delta(
        self,
        addr: int,
        verify: bool = True,
        claimed: set[int] | None = None,
        k_neighbors: int = 1,
    ) -> RelocationResult | None:
        """
        Phase 2/4: Estimate target address from nearest resolved neighbor's delta.

        If verify=True (Phase 2), confirms the estimate by checking that 16 bytes
        at the source address match 16 bytes at the estimated target address.
        If verify=False (Phase 4), returns the estimate without verification.

        When k_neighbors > 1 (used for Phase 4), tries multiple nearest neighbors
        and prefers neighbors within 0x10000 of the source address (same region).
        Skips estimates that land on already-claimed target addresses.
        """
        if not self._resolved:
            return None
        if claimed is None:
            claimed = set()

        # Sort resolved addresses by distance, preferring same-region neighbors
        resolved_items = [
            (ra, r) for ra, r in self._resolved.items() if r.target_addr is not None
        ]
        if not resolved_items:
            return None

        if k_neighbors <= 1:
            # Original fast path for Phase 2: single nearest neighbor
            nearest_addr = min(resolved_items, key=lambda x: abs(x[0] - addr))[0]
            neighbors = [(nearest_addr, self._resolved[nearest_addr])]
        else:
            # Phase 4: try k neighbors, preferring same region (within 0x10000)
            same_region = [
                (ra, r) for ra, r in resolved_items if abs(ra - addr) <= 0x10000
            ]
            other_region = [
                (ra, r) for ra, r in resolved_items if abs(ra - addr) > 0x10000
            ]
            # Sort each group by distance
            same_region.sort(key=lambda x: abs(x[0] - addr))
            other_region.sort(key=lambda x: abs(x[0] - addr))
            # Same-region neighbors first, then others
            neighbors = (same_region + other_region)[:k_neighbors]

        for nearest_addr, nearest_result in neighbors:
            delta = nearest_result.target_addr - nearest_result.source_addr
            estimated = addr + delta

            # Bounds check
            if estimated < 0 or estimated >= len(self.target_rom):
                continue

            # Skip already-claimed targets
            if estimated in claimed:
                continue

            if verify:
                # Verify with 16-byte comparison
                check_len = min(
                    16, len(self.ref_rom) - addr, len(self.target_rom) - estimated
                )
                if check_len < 4:
                    continue
                if (
                    self.ref_rom[addr : addr + check_len]
                    != self.target_rom[estimated : estimated + check_len]
                ):
                    continue

            phase = 2 if verify else 4
            confidence = "high" if verify else "low"
            return RelocationResult(
                source_addr=addr,
                target_addr=estimated,
                phase=phase,
                confidence=confidence,
            )

        return None

    def disambiguate_multi(
        self,
        addr: int,
        context_sizes: tuple[int, ...] | None = None,
        max_candidates: int = 20,
        claimed: set[int] | None = None,
    ) -> RelocationResult | None:
        """
        Phase 3: For addresses with 2-20 context matches, pick the candidate
        closest to the median delta of nearby resolved addresses (within 8KB).

        Candidates already in `claimed` are excluded to prevent collisions.
        """
        if context_sizes is None:
            context_sizes = self._DEFAULT_CONTEXT_SIZES
        if claimed is None:
            claimed = set()

        # Collect nearby deltas (within 8KB)
        nearby_deltas = []
        for resolved_addr, result in self._resolved.items():
            if abs(resolved_addr - addr) <= 8192 and result.target_addr is not None:
                nearby_deltas.append(result.target_addr - result.source_addr)

        if not nearby_deltas:
            return None

        median_delta = statistics.median(nearby_deltas)

        # Try context sizes, looking for multi-match cases
        for ctx_size in context_sizes:
            ctx_start = max(0, addr - ctx_size)
            ctx_end = min(len(self.ref_rom), addr + ctx_size)
            context = self.ref_rom[ctx_start:ctx_end]

            if len(context) < 4:
                continue

            matches = find_pattern(self.target_rom, context)

            if 2 <= len(matches) <= max_candidates:
                offset_in_ctx = addr - ctx_start
                candidates = [m + offset_in_ctx for m in matches]

                # Filter out already-claimed target addresses
                available = [c for c in candidates if c not in claimed]
                if not available:
                    continue

                # Pick candidate closest to median delta
                best = min(available, key=lambda c: abs((c - addr) - median_delta))
                return RelocationResult(
                    source_addr=addr,
                    target_addr=best,
                    phase=3,
                    confidence="medium",
                    context_size=ctx_size,
                )

        return None

    def relocate_all(
        self, addresses: list[int]
    ) -> tuple[dict[int, RelocationResult], list[int], int]:
        """
        Run all 4 phases sequentially on the given addresses.

        Each phase builds on resolved results from prior phases.
        Addresses are sorted before processing so nearest-neighbor delta works well.

        Returns (results, merged_addrs, collisions_resolved) where:
        - merged_addrs: source addresses with legitimate merge collisions
        - collisions_resolved: count of collisions fixed by eviction + re-resolve
        """
        sorted_addrs = sorted(addresses)
        self._resolved = {}
        self._claimed: set[int] = set()
        unresolved = list(sorted_addrs)

        # Phase 1 — Unique byte-context match
        still_unresolved = []
        for addr in unresolved:
            result = self.find_unique(addr)
            if result:
                self._resolved[addr] = result
                self._claimed.add(result.target_addr)
            else:
                still_unresolved.append(addr)
        logger.info(
            "Phase 1 (unique context): %d/%d resolved",
            len(self._resolved),
            len(sorted_addrs),
        )
        unresolved = still_unresolved

        # Phase 2 — Delta estimation + verification
        still_unresolved = []
        for addr in unresolved:
            result = self.find_by_delta(addr, verify=True, claimed=self._claimed)
            if result:
                self._resolved[addr] = result
                self._claimed.add(result.target_addr)
            else:
                still_unresolved.append(addr)
        phase2_count = sum(1 for r in self._resolved.values() if r.phase == 2)
        logger.info(
            "Phase 2 (verified delta): +%d, %d/%d total",
            phase2_count,
            len(self._resolved),
            len(sorted_addrs),
        )
        unresolved = still_unresolved

        # Phase 3 — Multi-match disambiguation (with claimed filter)
        still_unresolved = []
        for addr in unresolved:
            result = self.disambiguate_multi(addr, claimed=self._claimed)
            if result:
                self._resolved[addr] = result
                self._claimed.add(result.target_addr)
            else:
                still_unresolved.append(addr)
        phase3_count = sum(1 for r in self._resolved.values() if r.phase == 3)
        logger.info(
            "Phase 3 (disambiguation): +%d, %d/%d total",
            phase3_count,
            len(self._resolved),
            len(sorted_addrs),
        )
        unresolved = still_unresolved

        # Phase 4 — Unverified delta (k-nearest neighbors, same-region preference)
        still_unresolved = []
        for addr in unresolved:
            result = self.find_by_delta(
                addr, verify=False, claimed=self._claimed, k_neighbors=5
            )
            if result:
                self._resolved[addr] = result
                self._claimed.add(result.target_addr)
            else:
                still_unresolved.append(addr)
        phase4_count = sum(1 for r in self._resolved.values() if r.phase == 4)
        logger.info(
            "Phase 4 (unverified delta): +%d, %d/%d total",
            phase4_count,
            len(self._resolved),
            len(sorted_addrs),
        )

        if still_unresolved:
            logger.warning(
                "%d addresses could not be relocated: %s",
                len(still_unresolved),
                [f"0x{a:X}" for a in still_unresolved[:10]],
            )

        # Post-phase collision resolution
        merged, collisions_resolved = self._resolve_collisions(still_unresolved)

        return dict(self._resolved), merged, collisions_resolved

    def _resolve_collisions(self, unresolved: list[int]) -> tuple[list[int], int]:
        """
        Detect and resolve remaining target-address collisions.

        For each collision group:
        - If source addresses have identical data (32 bytes) → legitimate merge,
          flag as confidence="merged"
        - If different data → keep highest-confidence phase, evict others

        Evicted addresses get one more pass of Phase 2→4.
        Returns (merged_addrs, collisions_resolved).
        """
        # Build reverse map: target_addr -> [source_addrs]
        target_to_sources: dict[int, list[int]] = {}
        for src_addr, result in self._resolved.items():
            if result.target_addr is not None:
                target_to_sources.setdefault(result.target_addr, []).append(src_addr)

        # Find collision groups (target mapped by 2+ sources)
        collision_groups = {
            t: srcs for t, srcs in target_to_sources.items() if len(srcs) > 1
        }

        if not collision_groups:
            return [], 0

        merged_addrs: list[int] = []
        evicted: list[int] = []
        compare_len = 32

        for target_addr, src_addrs in collision_groups.items():
            # Check if all sources have identical data at their source locations
            data_samples = []
            for sa in src_addrs:
                end = min(sa + compare_len, len(self.ref_rom))
                data_samples.append(self.ref_rom[sa:end])

            all_identical = all(d == data_samples[0] for d in data_samples[1:])

            if all_identical:
                # Legitimate merge — flag all with confidence="merged"
                for sa in src_addrs:
                    self._resolved[sa] = RelocationResult(
                        source_addr=sa,
                        target_addr=target_addr,
                        phase=self._resolved[sa].phase,
                        confidence="merged",
                        context_size=self._resolved[sa].context_size,
                    )
                merged_addrs.extend(src_addrs)
                logger.debug(
                    "Merged collision at 0x%X: %s",
                    target_addr,
                    [f"0x{a:X}" for a in src_addrs],
                )
            else:
                # Keep the mapping with the best phase (lowest number = highest confidence)
                best_src = min(src_addrs, key=lambda a: self._resolved[a].phase)
                for sa in src_addrs:
                    if sa != best_src:
                        # Evict: remove from resolved and claimed
                        del self._resolved[sa]
                        # Don't remove from claimed — the winner still holds it
                        evicted.append(sa)
                logger.debug(
                    "Collision at 0x%X: kept 0x%X (phase %d), evicted %s",
                    target_addr,
                    best_src,
                    self._resolved[best_src].phase,
                    [f"0x{a:X}" for a in src_addrs if a != best_src],
                )

        if not evicted:
            return merged_addrs, 0

        logger.info(
            "Collision resolution: %d merged, %d evicted for re-resolve",
            len(merged_addrs),
            len(evicted),
        )

        # Re-resolve evicted addresses with Phase 2→4
        collisions_resolved = 0
        evicted.sort()
        retry_unresolved = list(evicted)

        # Phase 2 retry
        still_unresolved = []
        for addr in retry_unresolved:
            result = self.find_by_delta(addr, verify=True, claimed=self._claimed)
            if result:
                self._resolved[addr] = result
                self._claimed.add(result.target_addr)
                collisions_resolved += 1
            else:
                still_unresolved.append(addr)
        retry_unresolved = still_unresolved

        # Phase 3 retry
        still_unresolved = []
        for addr in retry_unresolved:
            result = self.disambiguate_multi(addr, claimed=self._claimed)
            if result:
                self._resolved[addr] = result
                self._claimed.add(result.target_addr)
                collisions_resolved += 1
            else:
                still_unresolved.append(addr)
        retry_unresolved = still_unresolved

        # Phase 4 retry
        for addr in retry_unresolved:
            result = self.find_by_delta(
                addr, verify=False, claimed=self._claimed, k_neighbors=5
            )
            if result:
                self._resolved[addr] = result
                self._claimed.add(result.target_addr)
                collisions_resolved += 1

        logger.info(
            "Re-resolve pass: %d/%d evicted addresses recovered",
            collisions_resolved,
            len(evicted),
        )

        return merged_addrs, collisions_resolved


# Regex for scaling name: decimal address with optional _suffix
_SCALING_NAME_RE = re.compile(r"^(\d+)(_.*)?$")


def _parse_scaling_name(name: str) -> tuple[int, str] | None:
    """Parse a scaling name into (decimal_address, suffix) or None."""
    m = _SCALING_NAME_RE.match(name)
    if m:
        return int(m.group(1)), m.group(2) or ""
    return None


def _rebuild_scaling_name(new_addr: int, suffix: str) -> str:
    """Reconstruct scaling name from new address + original suffix."""
    return f"{new_addr}{suffix}"


class DefinitionRelocator:
    """
    Generate a relocated XML definition for a new ROM calibration.

    Takes a source XML definition, source ROM, and target ROM, then:
    1. Collects all unique addresses from table elements
    2. Runs DataMatcher to relocate addresses
    3. Updates the XML tree in-place (RomID, addresses, scaling names)
    4. Validates and serializes
    """

    def __init__(self, source_xml: Path, source_rom: bytes, target_rom: bytes):
        if not validate_rom_size(source_rom):
            raise ValueError("Source ROM must be exactly 1 MB")
        if not validate_rom_size(target_rom):
            raise ValueError("Target ROM must be exactly 1 MB")

        self.source_xml = source_xml
        self.source_rom = source_rom
        self.target_rom = target_rom

    def generate(self) -> DefinitionGenResult:
        """Generate the relocated XML definition."""
        # Parse source XML
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        tree = etree.parse(str(self.source_xml), parser)
        root = tree.getroot()

        if root.tag == "rom":
            rom_elem = root
        else:
            rom_elem = root.find(".//rom")
            if rom_elem is None:
                raise ValueError("No <rom> element found in source XML")

        # Step 1: Collect all unique addresses
        addr_set = set()
        for table_elem in rom_elem.iter("table"):
            addr_str = table_elem.get("address")
            if addr_str:
                addr_set.add(int(addr_str, 16))

        addresses = sorted(addr_set)
        logger.info("Collected %d unique addresses from XML", len(addresses))

        # Step 2: Run DataMatcher
        matcher = DataMatcher(self.source_rom, self.target_rom)
        results, merged_addrs, collisions_resolved = matcher.relocate_all(addresses)

        # Build address mapping: source_addr -> target_addr
        addr_map: dict[int, int] = {}
        for addr, result in results.items():
            if result.target_addr is not None:
                addr_map[addr] = result.target_addr

        # Step 3: Update RomID
        warnings = []
        target_cal_id = get_cal_id(self.target_rom)
        cal_id_str = target_cal_id.decode("ascii", errors="replace").rstrip("\x00")

        romid_elem = rom_elem.find("romid")
        if romid_elem is not None:
            self._update_romid(romid_elem, cal_id_str, target_cal_id)

        # Step 4: Update table addresses
        for table_elem in rom_elem.iter("table"):
            addr_str = table_elem.get("address")
            if addr_str:
                old_addr = int(addr_str, 16)
                if old_addr in addr_map:
                    new_addr = addr_map[old_addr]
                    table_elem.set("address", format(new_addr, "x"))
                else:
                    warnings.append(
                        f"Table address 0x{old_addr:X} could not be relocated"
                    )

        # Step 5: Update scaling names and references
        self._update_scalings(rom_elem, addr_map, warnings)

        # Step 6: Validate
        self._validate(rom_elem, warnings)

        # Serialize
        xml_bytes = etree.tostring(
            tree,
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        )

        # Build phase counts
        phase_counts: dict[int, int] = {}
        for r in results.values():
            phase_counts[r.phase] = phase_counts.get(r.phase, 0) + 1

        low_confidence = [
            r.source_addr for r in results.values() if r.confidence == "low"
        ]
        failed = [a for a in addresses if a not in addr_map]

        return DefinitionGenResult(
            xml_bytes=xml_bytes,
            total_addresses=len(addresses),
            resolved=len(addr_map),
            phase_counts=phase_counts,
            low_confidence=low_confidence,
            failed=failed,
            warnings=warnings,
            merged=merged_addrs,
            collisions_resolved=collisions_resolved,
        )

    def _update_romid(
        self, romid_elem: etree._Element, cal_id_str: str, cal_id_bytes: bytes
    ):
        """Update RomID fields for the target calibration."""
        # Find the cal-ID offset used in the target ROM
        cal_id_offset = None
        for offset in CAL_ID_OFFSETS:
            if len(self.target_rom) >= offset + 6:
                if self.target_rom[offset : offset + 6] == cal_id_bytes:
                    cal_id_offset = offset
                    break

        fields = {
            "xmlid": cal_id_str,
            "ecuid": cal_id_str,
            "internalidstring": cal_id_str,
        }
        if cal_id_offset is not None:
            fields["internalidaddress"] = format(cal_id_offset, "x")

        for tag, value in fields.items():
            elem = romid_elem.find(tag)
            if elem is not None:
                elem.text = value

    def _update_scalings(
        self,
        rom_elem: etree._Element,
        addr_map: dict[int, int],
        warnings: list[str],
    ):
        """Update scaling names and table scaling references."""
        # Build scaling name rename map: old_name -> new_name
        rename_map: dict[str, str] = {}

        for scaling_elem in rom_elem.findall("scaling"):
            old_name = scaling_elem.get("name")
            if not old_name:
                continue

            parsed = _parse_scaling_name(old_name)
            if parsed is None:
                continue

            dec_addr, suffix = parsed
            if dec_addr in addr_map:
                new_dec = addr_map[dec_addr]
                new_name = _rebuild_scaling_name(new_dec, suffix)
                rename_map[old_name] = new_name
                scaling_elem.set("name", new_name)
            else:
                warnings.append(
                    f"Scaling '{old_name}' address 0x{dec_addr:X} not relocated"
                )

        # Update table scaling references
        for table_elem in rom_elem.iter("table"):
            scaling_ref = table_elem.get("scaling")
            if scaling_ref and scaling_ref in rename_map:
                table_elem.set("scaling", rename_map[scaling_ref])

    def _validate(
        self,
        rom_elem: etree._Element,
        warnings: list[str],
    ):
        """Validate relocated addresses are in bounds and unique."""
        target_size = len(self.target_rom)
        seen_addrs: dict[int, str] = {}

        for table_elem in rom_elem.iter("table"):
            addr_str = table_elem.get("address")
            if not addr_str:
                continue

            addr = int(addr_str, 16)
            name = table_elem.get("name", "<unnamed>")

            if addr >= target_size:
                warnings.append(
                    f"Address 0x{addr:X} for '{name}' is out of bounds "
                    f"(ROM size: 0x{target_size:X})"
                )

            if addr in seen_addrs:
                # Duplicate addresses can be legitimate (axis reuse)
                pass

            seen_addrs[addr] = name
