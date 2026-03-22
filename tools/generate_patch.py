#!/usr/bin/env python3
"""
Generate a RomDrop-compatible patch for a new ROM calibration.

Uses existing reference pairs (stock ROM + .patch file) to learn the patch
pattern and apply it to a calibration that RomDrop doesn't cover.

Usage:
    python tools/generate_patch.py \\
        --target examples/SW-LFNPEA.BIN \\
        --refs-dir /path/to/stock_roms \\
        --patches-dir /path/to/patches \\
        -o lfnpea.patch

The refs-dir should contain stock ROM .bin files and patches-dir should
contain the corresponding .patch files (named by calibration ID).
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ecu.patch_generator import generate_patch
from src.ecu.rom_utils import get_cal_id, detect_vehicle_generation


def main():
    parser = argparse.ArgumentParser(
        description="Generate a patch for a new ROM calibration"
    )
    parser.add_argument(
        "--target",
        required=True,
        type=Path,
        help="Path to the target stock ROM (.bin)",
    )
    parser.add_argument(
        "--refs-dir",
        required=True,
        type=Path,
        help="Directory containing stock ROM files",
    )
    parser.add_argument(
        "--patches-dir",
        required=True,
        type=Path,
        help="Directory containing .patch files",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output patch file path (default: <cal-id>.patch)",
    )
    parser.add_argument(
        "--max-refs",
        type=int,
        default=10,
        help="Maximum reference pairs to use for consensus (default: 10)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if not args.target.exists():
        print(f"Error: target ROM not found: {args.target}", file=sys.stderr)
        sys.exit(1)
    if not args.refs_dir.is_dir():
        print(f"Error: refs directory not found: {args.refs_dir}", file=sys.stderr)
        sys.exit(1)
    if not args.patches_dir.is_dir():
        print(
            f"Error: patches directory not found: {args.patches_dir}", file=sys.stderr
        )
        sys.exit(1)

    target_rom = args.target.read_bytes()
    cal_id = get_cal_id(target_rom).decode("ascii", errors="replace")
    gen = detect_vehicle_generation(target_rom)

    print(f"Target: {cal_id} ({gen})")
    print(f"References: {args.refs_dir}")
    print(f"Patches: {args.patches_dir}")
    print()

    result = generate_patch(
        target_rom,
        args.refs_dir,
        args.patches_dir,
        max_refs=args.max_refs,
    )

    # Output path
    output = args.output or Path(f"{cal_id.lower().rstrip(chr(0))}.patch")

    output.write_bytes(result.patch_data)
    print(f"\nPatch written to: {output}")
    print(f"  Hooks found: {result.hooks_found}/{result.hooks_total}")
    print(f"  0xFF bytes copied: {result.ff_bytes_copied}")
    print(f"  Addresses fixed: {result.addresses_fixed}")

    if result.hooks_missed:
        print(f"\n  MISSED HOOKS ({len(result.hooks_missed)}):")
        for h in result.hooks_missed:
            print(f"    0x{h.addr:06X} [{h.size}B] {h.hook_type.value}")

    if result.warnings:
        print(f"\n  WARNINGS ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"    {w}")

    # Exit code: 0 if all hooks found, 1 if some missed
    if result.hooks_missed:
        sys.exit(1)


if __name__ == "__main__":
    main()
