"""
ROM Definition XML Parser

Parses RomDrop-style XML definition files into RomDefinition objects.
"""

from lxml import etree
from typing import Optional
from pathlib import Path

from .rom_definition import (
    RomDefinition,
    RomID,
    Scaling,
    Table,
    TableType,
    AxisType
)


class DefinitionParser:
    """
    Parser for ROM definition XML files
    """

    def __init__(self, xml_path: str):
        """
        Initialize parser with path to XML definition file

        Args:
            xml_path: Path to ROM definition XML file
        """
        self.xml_path = Path(xml_path)
        if not self.xml_path.exists():
            raise FileNotFoundError(f"Definition file not found: {xml_path}")

    def parse(self) -> RomDefinition:
        """
        Parse the XML file and return a RomDefinition object

        Returns:
            RomDefinition: Complete ROM definition
        """
        tree = etree.parse(str(self.xml_path))
        root = tree.getroot()

        # Parse ROM element (should be only one)
        rom_element = root.find('.//rom')
        if rom_element is None:
            raise ValueError("No <rom> element found in XML")

        # Parse ROM ID
        romid = self._parse_romid(rom_element)

        # Parse all scaling definitions
        scalings = self._parse_scalings(rom_element)

        # Parse all table definitions
        tables = self._parse_tables(rom_element)

        return RomDefinition(
            romid=romid,
            scalings=scalings,
            tables=tables
        )

    def _parse_romid(self, rom_element) -> RomID:
        """Parse ROM identification section"""
        romid_elem = rom_element.find('romid')
        if romid_elem is None:
            raise ValueError("No <romid> element found")

        def get_text(tag: str, default: str = "") -> str:
            elem = romid_elem.find(tag)
            return elem.text.strip() if elem is not None and elem.text else default

        return RomID(
            xmlid=get_text('xmlid'),
            internalidaddress=get_text('internalidaddress'),
            internalidstring=get_text('internalidstring'),
            ecuid=get_text('ecuid'),
            make=get_text('make'),
            model=get_text('model'),
            flashmethod=get_text('flashmethod'),
            memmodel=get_text('memmodel'),
            checksummodule=get_text('checksummodule'),
            market=get_text('market') or None,
            submodel=get_text('submodel') or None,
            transmission=get_text('transmission') or None,
            year=get_text('year') or None,
        )

    def _parse_scalings(self, rom_element) -> dict:
        """Parse all scaling definitions into a dictionary"""
        scalings = {}

        for scaling_elem in rom_element.findall('.//scaling'):
            name = scaling_elem.get('name')
            if not name:
                continue  # Skip scalings without names

            scaling = Scaling(
                name=name,
                units=scaling_elem.get('units', ''),
                toexpr=scaling_elem.get('toexpr', 'x'),
                frexpr=scaling_elem.get('frexpr', 'x'),
                format=scaling_elem.get('format', '%0.2f'),
                min=float(scaling_elem.get('min', '0')),
                max=float(scaling_elem.get('max', '0')),
                inc=float(scaling_elem.get('inc', '1')),
                storagetype=scaling_elem.get('storagetype', 'float'),
                endian=scaling_elem.get('endian', 'big'),
            )

            scalings[name] = scaling

        return scalings

    def _parse_tables(self, rom_element) -> list:
        """
        Parse all table definitions

        Returns list of top-level tables (not axis children)
        """
        tables = []

        # Find all top-level table elements (direct children of rom, not nested in other tables)
        # We need to handle the hierarchy: some tables contain child axis tables
        for table_elem in rom_element.findall('./table'):
            # Only parse if it has required attributes (top-level tables)
            if table_elem.get('address') and table_elem.get('type'):
                table = self._parse_table(table_elem)
                if table:
                    tables.append(table)

        return tables

    def _parse_table(self, table_elem) -> Optional[Table]:
        """Parse a single table element and its children"""
        # Get table type
        type_str = table_elem.get('type')
        if not type_str:
            return None

        # Determine if this is an axis table
        axis_type = None
        if type_str in ['X Axis', 'Y Axis']:
            axis_type = AxisType.X_AXIS if type_str == 'X Axis' else AxisType.Y_AXIS
            table_type = TableType.ONE_D  # Axes are always 1D
        else:
            try:
                table_type = TableType(type_str)
            except ValueError:
                return None  # Unknown type

        # Parse basic attributes
        table = Table(
            name=table_elem.get('name', 'Unnamed'),
            address=table_elem.get('address', '0'),
            elements=int(table_elem.get('elements', '0')),
            scaling=table_elem.get('scaling', ''),
            type=table_type,
            level=int(table_elem.get('level', '1')),
            category=table_elem.get('category', ''),
            swapxy=table_elem.get('swapxy', 'false').lower() == 'true',
            axis_type=axis_type,
        )

        # Parse child tables (axes for 2D/3D tables)
        for child_elem in table_elem.findall('./table'):
            child_table = self._parse_table(child_elem)
            if child_table:
                table.children.append(child_table)

        return table


def load_definition(xml_path: str) -> RomDefinition:
    """
    Convenience function to load a ROM definition from XML file

    Args:
        xml_path: Path to XML definition file

    Returns:
        RomDefinition: Parsed ROM definition
    """
    parser = DefinitionParser(xml_path)
    return parser.parse()
