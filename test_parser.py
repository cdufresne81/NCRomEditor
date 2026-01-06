#!/usr/bin/env python3
"""
Quick test of the ROM definition parser
"""

import sys
from src.core.definition_parser import load_definition

def main():
    xml_path = "metadata/lf9veb.xml"

    print("Loading ROM definition from:", xml_path)
    print()

    try:
        definition = load_definition(xml_path)

        # Print ROM ID info
        print("=== ROM ID ===")
        print(f"  XML ID: {definition.romid.xmlid}")
        print(f"  Make/Model: {definition.romid.make} {definition.romid.model}")
        print(f"  ECU ID: {definition.romid.ecuid}")
        print(f"  Memory Model: {definition.romid.memmodel}")
        print(f"  Checksum Module: {definition.romid.checksummodule}")
        print(f"  Internal ID Address: {definition.romid.internalidaddress}")
        print()

        # Print scaling stats
        print("=== Scalings ===")
        print(f"  Total scalings: {len(definition.scalings)}")

        # Show a few example scalings
        print("  Example scalings:")
        for i, (name, scaling) in enumerate(list(definition.scalings.items())[:3]):
            print(f"    {name}: {scaling.storagetype} ({scaling.endian}), "
                  f"toexpr='{scaling.toexpr}', range=[{scaling.min}, {scaling.max}]")
        print()

        # Print table stats
        print("=== Tables ===")
        print(f"  Total tables: {len(definition.tables)}")

        # Count by type
        type_counts = {}
        for table in definition.tables:
            if not table.is_axis:  # Don't count axis tables
                type_str = table.type.value
                type_counts[type_str] = type_counts.get(type_str, 0) + 1

        print("  By type:")
        for table_type, count in sorted(type_counts.items()):
            print(f"    {table_type}: {count}")
        print()

        # Group by category
        categories = definition.get_tables_by_category()
        print(f"  Categories: {len(categories)}")
        print("  Top categories by table count:")
        sorted_cats = sorted(categories.items(), key=lambda x: len(x[1]), reverse=True)
        for category, tables in sorted_cats[:10]:
            print(f"    {category}: {len(tables)} tables")
        print()

        # Show a few example tables
        print("=== Example Tables ===")

        # Find some interesting tables
        for table in definition.tables:
            if table.is_axis:
                continue
            if "Spark Target" in table.name and table.type.value == "3D":
                print(f"  {table.name}")
                print(f"    Type: {table.type.value}")
                print(f"    Category: {table.category}")
                print(f"    Address: 0x{table.address}")
                print(f"    Elements: {table.elements}")
                print(f"    Scaling: {table.scaling}")
                if table.x_axis:
                    print(f"    X Axis: {table.x_axis.elements} elements at 0x{table.x_axis.address}")
                if table.y_axis:
                    print(f"    Y Axis: {table.y_axis.elements} elements at 0x{table.y_axis.address}")
                print()
                break

        print("✓ Parser test successful!")
        return 0

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
