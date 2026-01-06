# ROM Definition Metadata

This directory contains ROM definition files (XML) that describe the structure and location of data within ECU ROM binary files.

## Files

### lf9veb.xml
ROM definition file for LF9VEB ECU (NC Miata / MX-5).

- Format: RomDrop XML definition
- Contains: 511 table definitions, 838 scaling definitions
- Categories: Fuel, Spark, DBW, Sensors, DTC, etc.
- ECU Model: SH7058
- Checksum Module: 21053000

## ROM Definition Format

ROM definitions describe:
- **Scalings**: How to convert binary values to/from display units (e.g., raw bytes → degrees)
- **Tables**: Location and structure of calibration maps
  - 1D: Single values or constants
  - 2D: Arrays (e.g., values vs RPM)
  - 3D: Grids/maps (e.g., fuel/timing vs RPM and Load)

Each table definition includes:
- Address in ROM (hex)
- Number of elements
- Data type (float, uint8, etc.)
- Scaling reference
- Category for UI organization

## Usage

These definition files are automatically loaded by the application. The current hardcoded definition is `metadata/lf9veb.xml`.

For more details on the format, see `docs/ROM_DEFINITION_FORMAT.md`.
