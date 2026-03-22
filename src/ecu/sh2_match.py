"""
SH-2 instruction matching engine for cross-calibration ROM analysis.

The SH7058 CPU uses fixed 16-bit instructions. When the same source code is
compiled for different calibrations, register-register operations stay identical
but PC-relative displacements (loads, branches) shift. This module masks out
those variable fields so patterns can be matched across builds.

Instruction encoding reference (big-endian, 16-bit):
  0x9nXX  MOV.W @(disp,PC),Rn   -> mask XX (8-bit displacement)
  0xDnXX  MOV.L @(disp,PC),Rn   -> mask XX (8-bit displacement)
  0xAnXX  BRA   disp12           -> mask nXX (12-bit displacement)
  0xBnXX  BSR   disp12           -> mask nXX (12-bit displacement)
  0x89XX  BT    disp8            -> mask XX
  0x8BXX  BF    disp8            -> mask XX
  0x8DXX  BT/S  disp8            -> mask XX
  0x8FXX  BF/S  disp8            -> mask XX
"""

import logging
import struct

logger = logging.getLogger(__name__)

# Minimum ROM offset to search (skip vector table / boot code)
_ROM_CODE_START = 0x2000


def mask_sh2_instructions(data: bytes) -> bytes:
    """
    Mask displacement/immediate fields in SH-2 instructions.

    Replaces variable fields (PC-relative displacements, branch offsets) with
    zero while preserving opcode structure and register numbers. This produces
    a "signature" that is stable across different builds of the same code.

    Args:
        data: Raw bytes (should be 2-byte aligned for correct results).

    Returns:
        Masked copy of data with variable fields zeroed.
    """
    length = len(data) & ~1  # Truncate to even length
    result = bytearray(data[:length])
    for i in range(0, length, 2):
        hi = result[i]
        top4 = hi >> 4

        if top4 == 0x9:
            # MOV.W @(disp,PC),Rn — mask displacement byte
            result[i + 1] = 0x00
        elif top4 == 0xD:
            # MOV.L @(disp,PC),Rn — mask displacement byte
            result[i + 1] = 0x00
        elif top4 == 0xA:
            # BRA disp12 — mask all 12 bits
            result[i] = 0xA0
            result[i + 1] = 0x00
        elif top4 == 0xB:
            # BSR disp12 — mask all 12 bits
            result[i] = 0xB0
            result[i + 1] = 0x00
        elif hi in (0x89, 0x8B, 0x8D, 0x8F):
            # BT/BF/BT.S/BF.S disp8 — mask displacement
            result[i + 1] = 0x00

    return bytes(result)


def find_pattern(haystack: bytes, needle: bytes, start: int = 0) -> list[int]:
    """
    Find all occurrences of needle in haystack starting from offset start.

    Returns list of offsets where needle was found.
    """
    results = []
    pos = start
    while True:
        idx = haystack.find(needle, pos)
        if idx == -1:
            break
        results.append(idx)
        pos = idx + 1
    return results


def find_referencing_movl(
    rom: bytes, pool_addr: int, search_range: int = 4096
) -> int | None:
    """
    Find the MOV.L @(disp,PC),Rn instruction that references a literal pool entry.

    MOV.L @(disp,PC),Rn encoding: 0xDnXX
      Effective address = (PC & ~3) + 4 + disp*4
      where PC = address of the MOV.L instruction

    Args:
        rom: ROM data.
        pool_addr: Address of the 4-byte literal pool entry.
        search_range: How far back from pool_addr to search.

    Returns:
        Address of the MOV.L instruction, or None if not found.
    """
    aligned_pool = pool_addr & ~3
    search_start = max(_ROM_CODE_START, aligned_pool - search_range)
    if search_start % 2 != 0:
        search_start += 1

    for pc in range(search_start, aligned_pool, 2):
        if (rom[pc] >> 4) != 0xD:
            continue
        disp = rom[pc + 1]
        ea = (pc & ~3) + 4 + disp * 4
        if ea == aligned_pool:
            return pc

    return None


class SH2Matcher:
    """
    Cached SH-2 pattern matcher for cross-calibration ROM analysis.

    Pre-computes masked versions of ROMs so repeated searches are fast.
    """

    def __init__(self, ref_rom: bytes, target_rom: bytes):
        self.ref_rom = ref_rom
        self.target_rom = target_rom
        self._masked_target: bytes | None = None

    @property
    def masked_target(self) -> bytes:
        """Lazily compute masked target ROM (cached)."""
        if self._masked_target is None:
            code_region = self.target_rom[_ROM_CODE_START:]
            self._masked_target = mask_sh2_instructions(code_region)
        return self._masked_target

    def find_direct(
        self,
        addr: int,
        context_sizes: tuple[int, ...] = (8, 16, 32, 64, 128, 256),
    ) -> int | None:
        """
        Find addr's location in target_rom using direct byte-context matching.

        Tries progressively larger context windows around addr in ref_rom.
        Returns target address on unique match, None otherwise.
        """
        for ctx_size in context_sizes:
            ctx_start = max(_ROM_CODE_START, addr - ctx_size)
            ctx_end = min(len(self.ref_rom), addr + ctx_size)
            context = self.ref_rom[ctx_start:ctx_end]

            haystack = self.target_rom[_ROM_CODE_START:]
            matches = find_pattern(haystack, context)

            if len(matches) == 1:
                offset_in_ctx = addr - ctx_start
                return matches[0] + _ROM_CODE_START + offset_in_ctx

        return None

    def find_masked(
        self,
        addr: int,
        context_sizes: tuple[int, ...] = (8, 16, 32, 64, 128, 256),
    ) -> int | None:
        """
        Find addr's location using SH-2 instruction-masked matching.

        Masks out PC-relative displacements before comparing, so patterns
        match even when branch targets / literal pool offsets shift.
        """
        for ctx_size in context_sizes:
            ctx_start = max(_ROM_CODE_START, addr - ctx_size)
            if ctx_start % 2 != 0:
                ctx_start -= 1
            ctx_end = min(len(self.ref_rom), addr + ctx_size)
            # Ensure even-length context
            if (ctx_end - ctx_start) % 2 != 0:
                ctx_end -= 1

            ref_context = self.ref_rom[ctx_start:ctx_end]
            ref_masked = mask_sh2_instructions(ref_context)

            matches = find_pattern(self.masked_target, ref_masked)

            if len(matches) == 1:
                offset_in_ctx = addr - ctx_start
                return matches[0] + _ROM_CODE_START + offset_in_ctx

        return None

    def find_pool_backtrack(
        self,
        pool_addr: int,
        context_sizes: tuple[int, ...] = (12, 24, 48, 96, 128, 256),
    ) -> int | None:
        """
        Locate a literal pool entry by backtracking to the MOV.L that
        references it, matching code context, then following displacement.
        """
        movl_addr = find_referencing_movl(self.ref_rom, pool_addr)
        if movl_addr is None:
            return None

        # Find the corresponding MOV.L in target
        target_movl = self.find_masked(movl_addr, context_sizes)
        if target_movl is None:
            target_movl = self.find_direct(movl_addr, context_sizes)
        if target_movl is None:
            return None

        # Decode target MOV.L to compute new pool entry address
        disp = self.target_rom[target_movl + 1]
        target_pool = (target_movl & ~3) + 4 + disp * 4

        # Preserve sub-word offset within the pool entry
        offset_in_entry = pool_addr - (pool_addr & ~3)
        return target_pool + offset_in_entry

    def find_pool_by_value(self, pool_addr: int) -> int | None:
        """
        Locate a pool entry by finding the function it points to.

        Strategy:
        1. Read the 4-byte function address from the ref pool entry
        2. Find that function in the target ROM
        3. Search target ROM literal pools for a 4-byte entry containing
           the target function address
        4. Return the pool entry address in the target

        This handles cases where the MOV.L backtrack fails due to
        repetitive code patterns (e.g., dispatch tables).
        """
        aligned = pool_addr & ~3
        if aligned + 4 > len(self.ref_rom):
            return None

        # Read function address from reference pool entry
        ref_func_addr = struct.unpack_from(">I", self.ref_rom, aligned)[0]
        if not (_ROM_CODE_START <= ref_func_addr < len(self.ref_rom)):
            return None

        # Find this function in the target ROM
        target_func = self.find_direct(ref_func_addr)
        if target_func is None:
            target_func = self.find_masked(ref_func_addr)
        if target_func is None:
            return None

        # Search target ROM for pool entries containing target_func address
        target_func_bytes = struct.pack(">I", target_func)
        # Search in the same general area as the original pool entry
        # (pool entries are near the code that uses them)
        search_start = max(_ROM_CODE_START, aligned - 0x10000)
        search_end = min(len(self.target_rom), aligned + 0x10000)
        search_region = self.target_rom[search_start:search_end]

        matches = find_pattern(search_region, target_func_bytes)
        # Filter to 4-byte aligned matches
        aligned_matches = [
            m + search_start for m in matches if (m + search_start) % 4 == 0
        ]

        if len(aligned_matches) == 1:
            offset_in_entry = pool_addr - aligned
            return aligned_matches[0] + offset_in_entry

        return None

    def find_address(
        self,
        addr: int,
        is_pool_entry: bool = False,
    ) -> int | None:
        """
        Multi-strategy search for an address in the target ROM.

        Tries in order:
        1. Direct byte-context match (fast, works for most code hooks)
        2. SH-2 masked instruction match (handles PC-relative shifts)
        3. Literal pool backtracking via MOV.L (for pool entry redirects)
        4. Literal pool by function value (for pool entries in repetitive code)
        5. Direct match with very large context (last resort)
        """
        result = self.find_direct(addr)
        if result is not None:
            return result

        result = self.find_masked(addr)
        if result is not None:
            return result

        if is_pool_entry:
            result = self.find_pool_backtrack(addr)
            if result is not None:
                return result

            result = self.find_pool_by_value(addr)
            if result is not None:
                return result

        # Last resort: very large context (slow but handles edge cases)
        result = self.find_direct(addr, context_sizes=(512, 1024))
        if result is not None:
            return result

        return None
