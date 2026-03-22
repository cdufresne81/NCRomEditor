#!/usr/bin/env python3
"""
Generate an XML definition for a new ROM calibration by relocating addresses
from an existing definition.

Uses the source definition + source ROM to learn table locations, then finds
the corresponding locations in the target ROM via byte-context matching.

Usage:
    python tools/generate_definition.py \\
        --source-xml examples/metadata/lf9veb.xml \\
        --source-rom examples/lf9veb.bin \\
        --target-rom examples/SW-LFNPEA.BIN \\
        -o examples/metadata/lfnpea.xml -v
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ecu.definition_relocator import DefinitionRelocator
from src.ecu.rom_utils import get_cal_id, detect_vehicle_generation


def main():
    parser = argparse.ArgumentParser(
        description="Generate an XML definition for a new ROM calibration"
    )
    parser.add_argument(
        "--source-xml",
        required=True,
        type=Path,
        help="Path to the source XML definition",
    )
    parser.add_argument(
        "--source-rom",
        required=True,
        type=Path,
        help="Path to the source stock ROM (.bin)",
    )
    parser.add_argument(
        "--target-rom",
        required=True,
        type=Path,
        help="Path to the target stock ROM (.bin)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output XML file path (default: <cal-id>.xml in source XML directory)",
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

    # Validate inputs
    for label, path in [
        ("Source XML", args.source_xml),
        ("Source ROM", args.source_rom),
        ("Target ROM", args.target_rom),
    ]:
        if not path.exists():
            print(f"Error: {label} not found: {path}", file=sys.stderr)
            sys.exit(1)

    source_rom = args.source_rom.read_bytes()
    target_rom = args.target_rom.read_bytes()

    source_cal = get_cal_id(source_rom).decode("ascii", errors="replace").rstrip("\x00")
    target_cal = get_cal_id(target_rom).decode("ascii", errors="replace").rstrip("\x00")
    target_gen = detect_vehicle_generation(target_rom)

    print(f"Source: {source_cal} ({args.source_xml.name})")
    print(f"Target: {target_cal} ({target_gen})")
    print()

    relocator = DefinitionRelocator(args.source_xml, source_rom, target_rom)
    result = relocator.generate()

    # Output path
    output = args.output or args.source_xml.parent / f"{target_cal.lower()}.xml"
    output.write_bytes(result.xml_bytes)

    print(f"\nDefinition written to: {output}")
    print(f"  Addresses: {result.resolved}/{result.total_addresses} relocated")
    print(f"  Phase breakdown:")
    for phase in sorted(result.phase_counts):
        labels = {
            1: "unique context",
            2: "verified delta",
            3: "disambiguation",
            4: "unverified delta",
        }
        print(
            f"    Phase {phase} ({labels.get(phase, '?')}): {result.phase_counts[phase]}"
        )

    if result.merged:
        print(f"\n  MERGED TABLES ({len(result.merged)}):")
        for addr in result.merged[:20]:
            print(f"    0x{addr:06X}")
        if len(result.merged) > 20:
            print(f"    ... and {len(result.merged) - 20} more")

    if result.collisions_resolved:
        print(f"\n  Collisions resolved: {result.collisions_resolved}")

    if result.low_confidence:
        print(f"\n  LOW CONFIDENCE ({len(result.low_confidence)}):")
        for addr in result.low_confidence[:20]:
            print(f"    0x{addr:06X}")
        if len(result.low_confidence) > 20:
            print(f"    ... and {len(result.low_confidence) - 20} more")

    if result.failed:
        print(f"\n  FAILED ({len(result.failed)}):")
        for addr in result.failed[:20]:
            print(f"    0x{addr:06X}")
        if len(result.failed) > 20:
            print(f"    ... and {len(result.failed) - 20} more")

    if result.warnings:
        print(f"\n  WARNINGS ({len(result.warnings)}):")
        for w in result.warnings[:20]:
            print(f"    {w}")

    # Exit code: 0 if >95% resolved, 1 otherwise
    ratio = result.resolved / result.total_addresses if result.total_addresses else 0
    if ratio < 0.95:
        print(f"\n  Resolution rate {ratio:.1%} is below 95% threshold")
        sys.exit(1)


if __name__ == "__main__":
    main()
