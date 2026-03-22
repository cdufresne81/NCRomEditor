"""
Automated patch generator for new ROM calibrations.

Learns from existing reference pairs (stock ROM + patch file) to generate
patches for calibrations that RomDrop doesn't cover. Uses SH-2 instruction
matching to relocate hook sites across calibrations.

Architecture:
    1. Extract modification sites from reference pairs
    2. Classify each site (payload, handler, JSR, pool redirect, data, code)
    3. Copy 0xFF-region content (payload + handlers) from reference
    4. Relocate hook sites in the target ROM using multi-strategy matching
    5. Fix embedded addresses in 0xFF region using cross-reference comparison
    6. Build XOR patch mask with multi-reference consensus voting
"""

import logging
import struct
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .constants import ROM_SIZE, ROM_ID_OFFSET
from .rom_utils import detect_vehicle_generation, get_cal_id, validate_rom_size
from .sh2_match import SH2Matcher
from .exceptions import ROMValidationError

logger = logging.getLogger(__name__)

# Boundary between shifting payload blocks and fixed handler stubs
_HANDLER_REGION_START = 0x0FB000
# ROM code starts after vector table
_CODE_START = 0x2000
# Flash counter region (cleared by patch application, not a real hook)
_FLASH_COUNTER_START = 0xFFB00
_FLASH_COUNTER_END = 0xFFB08


class HookType(Enum):
    """Classification of a modification site."""

    PAYLOAD = "payload"  # Large code block in 0xFF region (shifting)
    HANDLER = "handler"  # Trampoline stub in 0xFF region (fixed address)
    JSR = "jsr"  # Single-byte JSR register change (0x4X -> 0x44)
    POOL = "pool"  # 3-byte literal pool redirect (-> 0x0F????)
    DATA = "data"  # Small data table patch
    CODE = "code"  # Code replacement (various sizes)


@dataclass
class HookSite:
    """A single modification site extracted from a reference pair."""

    addr: int  # Address in ROM
    size: int  # Number of modified bytes
    stock_bytes: bytes  # Original stock bytes
    patched_bytes: bytes  # Patched bytes from reference
    is_ff: bool  # Whether stock bytes are all 0xFF
    hook_type: HookType = HookType.CODE

    def __repr__(self):
        return (
            f"HookSite(0x{self.addr:06X}, {self.size}B, "
            f"{self.hook_type.value}, ff={self.is_ff})"
        )


@dataclass
class HookMatch:
    """Result of locating a hook site in a target ROM."""

    hook: HookSite
    target_addr: int  # Found address in target ROM
    ref_label: str  # Which reference found it
    confidence: int = 1  # Number of references agreeing


@dataclass
class PatchGenResult:
    """Result of patch generation."""

    patch_data: bytes  # 1MB XOR patch mask
    target_cal_id: bytes
    hooks_found: int
    hooks_total: int
    hooks_missed: list[HookSite] = field(default_factory=list)
    ff_bytes_copied: int = 0
    addresses_fixed: int = 0
    warnings: list[str] = field(default_factory=list)


def extract_mod_sites(
    stock_rom: bytes | bytearray, patched_rom: bytes | bytearray
) -> list[HookSite]:
    """
    Extract all modification sites between a stock and patched ROM.

    Scans from offset 0x2000 to end, finding contiguous runs of differing bytes.
    Skips the flash counter region (0xFFB00-0xFFB08) which is always cleared.
    """
    sites = []
    i = _CODE_START
    while i < ROM_SIZE:
        # Skip flash counter region
        if _FLASH_COUNTER_START <= i < _FLASH_COUNTER_END:
            i = _FLASH_COUNTER_END
            continue
        if stock_rom[i] != patched_rom[i]:
            start = i
            while i < ROM_SIZE and stock_rom[i] != patched_rom[i]:
                # Also skip flash counter within a run
                if _FLASH_COUNTER_START <= i < _FLASH_COUNTER_END:
                    break
                i += 1
            stock_bytes = bytes(stock_rom[start:i])
            patched_bytes = bytes(patched_rom[start:i])
            is_ff = all(b == 0xFF for b in stock_bytes)
            site = HookSite(
                addr=start,
                size=i - start,
                stock_bytes=stock_bytes,
                patched_bytes=bytes(patched_bytes),
                is_ff=is_ff,
            )
            classify_hook(site)
            sites.append(site)
        else:
            i += 1
    return sites


def classify_hook(site: HookSite) -> None:
    """Classify a hook site based on its characteristics."""
    if site.is_ff:
        if site.addr >= _HANDLER_REGION_START:
            site.hook_type = HookType.HANDLER
        else:
            site.hook_type = HookType.PAYLOAD
        return

    # JSR register change: single byte, patched = 0x44, stock is JSR @Rn
    if (
        site.size == 1
        and site.patched_bytes[0] == 0x44
        and (site.stock_bytes[0] >> 4) == 0x4
    ):
        site.hook_type = HookType.JSR
        return

    # Pool redirect: 3 bytes, patched points to handler region (0x0F????)
    if site.size == 3 and site.patched_bytes[0] == 0x0F:
        site.hook_type = HookType.POOL
        return

    # Data patches: small changes in high-address data regions
    if site.size <= 2 and site.addr >= 0x080000:
        site.hook_type = HookType.DATA
        return

    site.hook_type = HookType.CODE


def _apply_patch_xor(stock_rom: bytes, patch_data: bytes) -> bytearray:
    """Apply XOR patch to stock ROM, returning the patched ROM."""
    patched = bytearray(stock_rom)
    # Clear flash counter area (matches romdrop behavior)
    patched[0xFFB00:0xFFB08] = b"\xff" * 8
    for i in range(_CODE_START, ROM_SIZE):
        patched[i] ^= patch_data[i]
    return patched


def _find_reference_pairs(
    refs_dir: Path, patches_dir: Path, generation: str
) -> list[tuple[str, Path, Path]]:
    """
    Find matching stock ROM + patch file pairs for the given generation.

    Returns list of (cal_id_str, stock_path, patch_path).
    """
    pairs = []
    for patch_path in sorted(patches_dir.glob("*.patch")):
        cal_id = patch_path.stem.upper()
        # Try common naming patterns for stock ROMs
        stock_path = None
        for pattern in [
            refs_dir / f"{patch_path.stem}.bin",
            refs_dir / f"SW-{cal_id}.BIN",
            refs_dir / f"{cal_id}.bin",
            refs_dir / f"{cal_id}.BIN",
        ]:
            if pattern.exists():
                stock_path = pattern
                break

        if stock_path is None:
            continue

        # Check generation matches
        try:
            stock = stock_path.read_bytes()
            if not validate_rom_size(stock):
                continue
            gen = detect_vehicle_generation(stock)
            if gen == generation:
                pairs.append((cal_id, stock_path, patch_path))
        except Exception:
            continue

    return pairs


def _locate_hooks_with_reference(
    ref_stock: bytes,
    target_rom: bytes,
    hooks: list[HookSite],
) -> dict[int, int]:
    """
    Locate all non-0xFF hook sites in target_rom using one reference.

    Returns dict mapping ref_addr -> target_addr for found hooks.
    """
    matcher = SH2Matcher(ref_stock, target_rom)
    relocation_map = {}

    for hook in hooks:
        if hook.is_ff:
            continue

        is_pool = hook.hook_type == HookType.POOL
        target_addr = matcher.find_address(hook.addr, is_pool_entry=is_pool)

        if target_addr is not None:
            relocation_map[hook.addr] = target_addr

    return relocation_map


def _find_variable_positions(
    patched_a: bytes | bytearray, patched_b: bytes | bytearray, ff_sites: list[HookSite]
) -> list[tuple[int, int]]:
    """
    Compare two reference patched ROMs to find variable byte positions
    in the 0xFF regions (embedded calibration-specific addresses).

    Returns list of (addr, group_size) for each contiguous group of
    variable bytes.
    """
    variable_groups = []
    for site in ff_sites:
        i = site.addr
        end = site.addr + site.size
        while i < end:
            if patched_a[i] != patched_b[i]:
                group_start = i
                while i < end and patched_a[i] != patched_b[i]:
                    i += 1
                variable_groups.append((group_start, i - group_start))
            else:
                i += 1
    return variable_groups


def _extract_embedded_address(
    patched_rom: bytes, var_addr: int, var_size: int
) -> int | None:
    """
    Extract a ROM address from variable bytes in the 0xFF region.

    Reads 4 bytes at the 4-byte-aligned position containing the variable bytes
    and interprets as a big-endian 32-bit address.
    """
    # Align to 4-byte boundary
    aligned = var_addr & ~3
    if aligned + 4 > len(patched_rom):
        return None
    value = struct.unpack_from(">I", patched_rom, aligned)[0]
    # Valid ROM address range
    if _CODE_START <= value < ROM_SIZE:
        return value
    return None


def _fix_embedded_addresses(
    ref_stock_a: bytes,
    target_rom: bytes,
    patched_a: bytearray,
    patched_b: bytes,
    target_patched: bytearray,
    ff_sites: list[HookSite],
    relocation_map: dict[int, int],
) -> int:
    """
    Fix embedded stock ROM addresses in the 0xFF regions of target_patched.

    Uses cross-reference comparison to identify variable bytes, then resolves
    each embedded address in the target ROM.

    Returns count of addresses fixed.
    """
    variable_groups = _find_variable_positions(patched_a, patched_b, ff_sites)
    if not variable_groups:
        return 0

    logger.info("Found %d variable byte groups in 0xFF regions", len(variable_groups))

    # Build a matcher for resolving addresses
    matcher = SH2Matcher(ref_stock_a, target_rom)
    fixed_count = 0
    # Cache: ref_addr -> target_addr (avoid redundant lookups)
    addr_cache: dict[int, int | None] = dict(relocation_map)

    # Process groups, extracting 4-byte aligned addresses
    processed_aligned = set()
    for var_addr, var_size in variable_groups:
        aligned = var_addr & ~3
        if aligned in processed_aligned:
            continue
        processed_aligned.add(aligned)

        ref_addr = _extract_embedded_address(bytes(patched_a), var_addr, var_size)
        if ref_addr is None:
            # Not a ROM code address — might be intra-payload or data
            continue

        # Check if this address points to within the 0xFF region (intra-payload)
        if ref_stock_a[ref_addr] == 0xFF:
            # Intra-payload reference — already correct since we copied
            # payload at the same addresses
            continue

        # Resolve in target
        if ref_addr in addr_cache:
            target_addr = addr_cache[ref_addr]
        else:
            target_addr = matcher.find_address(ref_addr)
            addr_cache[ref_addr] = target_addr

        if target_addr is not None:
            # Write the resolved address into target_patched
            struct.pack_into(">I", target_patched, aligned, target_addr)
            fixed_count += 1
        else:
            logger.warning(
                "Could not resolve embedded address 0x%06X at 0x%06X",
                ref_addr,
                aligned,
            )

    return fixed_count


def generate_patch(
    target_rom: bytes,
    refs_dir: str | Path,
    patches_dir: str | Path,
    max_refs: int = 10,
) -> PatchGenResult:
    """
    Generate a patch for target_rom by learning from reference pairs.

    Args:
        target_rom: Stock ROM to generate patch for (1MB).
        refs_dir: Directory containing stock ROM files.
        patches_dir: Directory containing .patch files.
        max_refs: Maximum number of references to use for consensus.

    Returns:
        PatchGenResult with the generated patch data and statistics.
    """
    refs_dir = Path(refs_dir)
    patches_dir = Path(patches_dir)

    if not validate_rom_size(target_rom):
        raise ROMValidationError(
            f"Target ROM must be exactly {ROM_SIZE} bytes, got {len(target_rom)}"
        )

    target_cal_id = get_cal_id(target_rom)
    target_gen = detect_vehicle_generation(target_rom)
    logger.info(
        "Target: %s (%s)",
        target_cal_id.decode("ascii", errors="replace"),
        target_gen,
    )

    # Find reference pairs for the same generation
    pairs = _find_reference_pairs(refs_dir, patches_dir, target_gen)
    if not pairs:
        raise ROMValidationError(
            f"No reference pairs found for generation {target_gen}"
        )
    logger.info("Found %d reference pairs for %s", len(pairs), target_gen)

    # Load primary reference (first available)
    primary_label, primary_stock_path, primary_patch_path = pairs[0]
    primary_stock = primary_stock_path.read_bytes()
    primary_patch = primary_patch_path.read_bytes()
    patched_primary = _apply_patch_xor(primary_stock, primary_patch)
    logger.info("Primary reference: %s", primary_label)

    # Extract modification sites from primary reference
    all_sites = extract_mod_sites(primary_stock, patched_primary)
    ff_sites = [s for s in all_sites if s.is_ff]
    hook_sites = [s for s in all_sites if not s.is_ff]
    logger.info(
        "Extracted %d sites: %d 0xFF-region, %d hooks",
        len(all_sites),
        len(ff_sites),
        len(hook_sites),
    )

    # --- Phase 1: Copy 0xFF-region content from primary reference ---
    target_patched = bytearray(target_rom)
    # Clear flash counter
    target_patched[0xFFB00:0xFFB08] = b"\xff" * 8
    ff_bytes = 0
    ff_warnings = []

    for site in ff_sites:
        # Verify target has free space (0xFF) at these addresses
        target_region = target_rom[site.addr : site.addr + site.size]
        if not all(b == 0xFF for b in target_region):
            ff_warnings.append(
                f"Target ROM is not 0xFF at 0x{site.addr:06X}-"
                f"0x{site.addr + site.size - 1:06X} ({site.size}B) — "
                f"cannot place {site.hook_type.value}"
            )
            continue
        target_patched[site.addr : site.addr + site.size] = site.patched_bytes
        ff_bytes += site.size

    logger.info("Copied %d bytes of 0xFF-region content", ff_bytes)

    # --- Phase 2: Locate hook sites using multiple references ---
    # Each reference independently finds hooks in the target.
    # Collect all (target_addr, size, patched_bytes, label) tuples.
    # Group by target_addr for consensus voting.
    found_hooks: dict[int, list[tuple[int, bytes, str]]] = {}
    refs_used = 0

    for label, stock_path, patch_path in pairs[:max_refs]:
        ref_stock = stock_path.read_bytes()
        ref_patch = patch_path.read_bytes()
        ref_patched = _apply_patch_xor(ref_stock, ref_patch)

        ref_sites = extract_mod_sites(ref_stock, ref_patched)
        ref_hooks = [s for s in ref_sites if not s.is_ff]

        reloc = _locate_hooks_with_reference(ref_stock, target_rom, ref_hooks)
        refs_used += 1

        for ref_hook in ref_hooks:
            if ref_hook.addr not in reloc:
                continue
            target_addr = reloc[ref_hook.addr]
            if target_addr not in found_hooks:
                found_hooks[target_addr] = []
            found_hooks[target_addr].append(
                (ref_hook.size, ref_hook.patched_bytes, label)
            )

        logger.info(
            "Reference %s: found %d/%d hooks", label, len(reloc), len(ref_hooks)
        )

    # --- Phase 3: Apply found hooks to target ---
    hooks_found = 0
    hooks_missed = list(hook_sites)  # Start with all as missed
    warnings = list(ff_warnings)

    # Track which primary hooks are covered by found target addresses
    primary_covered = set()

    for target_addr, entries in sorted(found_hooks.items()):
        # Use patched_bytes from the entry with most consensus
        # (most references agreeing on the same patched_bytes)
        bytes_votes: dict[bytes, int] = {}
        for size, patched_bytes, _label in entries:
            bytes_votes[patched_bytes] = bytes_votes.get(patched_bytes, 0) + 1

        best_patched = max(bytes_votes, key=lambda b: bytes_votes[b])
        best_size = next(s for s, p, _ in entries if p == best_patched)

        end = target_addr + best_size
        if end > ROM_SIZE:
            warnings.append(f"Hook at target 0x{target_addr:06X} exceeds ROM size")
            continue

        target_patched[target_addr : target_addr + best_size] = best_patched
        hooks_found += 1

        # Mark any primary hooks with matching patched_bytes as covered
        for h in hook_sites:
            if h.patched_bytes == best_patched and h.addr not in primary_covered:
                primary_covered.add(h.addr)
                break

    # Update missed list
    hooks_missed = [h for h in hook_sites if h.addr not in primary_covered]
    # Adjust total to match the primary hook count
    hooks_total = len(hook_sites)

    logger.info(
        "Hooks: %d/%d found (used %d references)",
        hooks_found,
        hooks_total,
        refs_used,
    )

    # --- Phase 4: Fix embedded addresses in 0xFF region ---
    addresses_fixed = 0
    if len(pairs) >= 2:
        _, sec_stock_path, sec_patch_path = pairs[1]
        sec_stock = sec_stock_path.read_bytes()
        sec_patch = sec_patch_path.read_bytes()
        patched_secondary = _apply_patch_xor(sec_stock, sec_patch)

        # Build relocation map from found hooks
        # Maps primary hook addr -> target addr (for embedded address fixup)
        relocation_map = {}
        for target_addr, entries in found_hooks.items():
            for _size, patched_bytes, _label in entries:
                for h in hook_sites:
                    if h.patched_bytes == patched_bytes:
                        relocation_map[h.addr] = target_addr
                        break

        addresses_fixed = _fix_embedded_addresses(
            primary_stock,
            target_rom,
            bytearray(patched_primary),
            bytes(patched_secondary),
            target_patched,
            ff_sites,
            relocation_map,
        )
        logger.info("Fixed %d embedded addresses in 0xFF region", addresses_fixed)
    else:
        warnings.append(
            "Only 1 reference available — cannot fix embedded addresses "
            "in 0xFF region (need 2+ references to identify variable bytes)"
        )

    # --- Phase 5: Write ROM ID and cal-ID ---
    # ROM ID: copy from reference (same patch engine revision)
    rom_id_bytes = patched_primary[ROM_ID_OFFSET : ROM_ID_OFFSET + 4]
    target_patched[ROM_ID_OFFSET : ROM_ID_OFFSET + 4] = rom_id_bytes

    # --- Phase 6: Build XOR patch mask ---
    xor_mask = bytearray(ROM_SIZE)
    # Patch header: cal-ID at offset 0 (romdrop convention)
    xor_mask[0:6] = target_cal_id
    # XOR from 0x2000 to end
    for i in range(_CODE_START, ROM_SIZE):
        xor_mask[i] = target_rom[i] ^ target_patched[i]

    if hooks_missed:
        missed_types = {}
        for h in hooks_missed:
            t = h.hook_type.value
            missed_types[t] = missed_types.get(t, 0) + 1
        warnings.append(
            f"Missed {len(hooks_missed)} hooks: "
            + ", ".join(f"{v}x {k}" for k, v in missed_types.items())
        )

    return PatchGenResult(
        patch_data=bytes(xor_mask),
        target_cal_id=target_cal_id,
        hooks_found=hooks_found,
        hooks_total=len(hook_sites),
        hooks_missed=hooks_missed,
        ff_bytes_copied=ff_bytes,
        addresses_fixed=addresses_fixed,
        warnings=warnings,
    )
