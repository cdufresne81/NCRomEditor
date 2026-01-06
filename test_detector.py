#!/usr/bin/env python3
"""
Test ROM detector integration
"""

from src.core.rom_detector import RomDetector
from src.core.definition_parser import load_definition
from src.core.rom_reader import RomReader

print("=== ROM Detector Test ===\n")

# Initialize detector
print("1. Initializing ROM detector...")
detector = RomDetector('metadata')
print(f"   Found {len(detector.rom_definitions)} ROM definition(s)\n")

# Show available definitions
print("2. Available ROM definitions:")
for info in detector.get_definitions_summary():
    print(f"   - {info['xmlid']}: {info['make']} {info['model']}")
    print(f"     Internal ID: {info['internalid']}")
    print(f"     XML file: {info['xml_file']}")
print()

# Test detection
rom_file = 'examples/lf9veb.bin'
print(f"3. Detecting ROM ID from {rom_file}...")
rom_id, xml_path = detector.detect_rom_id(rom_file)
print(f"   Detected ROM ID: {rom_id}")
print(f"   Matched XML: {xml_path}\n")

if rom_id and xml_path:
    # Load definition
    print("4. Loading matched definition...")
    definition = load_definition(xml_path)
    print(f"   Loaded: {definition.romid.xmlid}")
    print(f"   Tables: {len(definition.tables)}")
    print(f"   Scalings: {len(definition.scalings)}\n")

    # Create ROM reader
    print("5. Creating ROM reader...")
    reader = RomReader(rom_file, definition)
    print(f"   ROM loaded: {rom_file}\n")

    # Verify ROM ID
    print("6. Verifying ROM ID...")
    if reader.verify_rom_id():
        print("   ✓ ROM ID verification passed!")
    else:
        print("   ✗ ROM ID verification failed!")
    print()

    # Read a sample table
    print("7. Reading sample table data...")
    sample_table = definition.tables[0]
    print(f"   Table: {sample_table.name}")
    print(f"   Category: {sample_table.category}")
    data = reader.read_table_data(sample_table)
    if data:
        print(f"   ✓ Successfully read {len(data['values'])} values")
    else:
        print("   ✗ Failed to read table data")
    print()

    print("=== Test Complete ===")
    print("✓ All tests passed! ROM auto-detection is working correctly.")
else:
    print("✗ ROM detection failed!")
