"""
ROM ID Detection and XML Matching

Automatically detects ROM ID from binary files and finds matching XML definitions.
"""

from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from lxml import etree


@dataclass
class RomIdInfo:
    """ROM ID information extracted from XML definition"""
    xml_path: Path
    xmlid: str
    internalidaddress: str
    internalidstring: str
    make: str
    model: str

    @property
    def internal_id_address_int(self) -> int:
        """Convert hex address string to integer"""
        return int(self.internalidaddress, 16)


class RomDetector:
    """
    Detects ROM ID from binary files and matches to XML definitions
    """

    def __init__(self, metadata_dir: str = "metadata"):
        """
        Initialize ROM detector

        Args:
            metadata_dir: Directory containing XML definition files
        """
        self.metadata_dir = Path(metadata_dir)
        if not self.metadata_dir.exists():
            raise FileNotFoundError(f"Metadata directory not found: {metadata_dir}")

        self.rom_definitions: List[RomIdInfo] = []
        self._scan_definitions()

    def _scan_definitions(self):
        """Scan all XML files in metadata directory and extract ROM ID info"""
        self.rom_definitions = []

        for xml_file in self.metadata_dir.glob("*.xml"):
            try:
                rom_info = self._extract_rom_id_from_xml(xml_file)
                if rom_info:
                    self.rom_definitions.append(rom_info)
            except Exception as e:
                print(f"Warning: Failed to parse {xml_file.name}: {e}")

    def _extract_rom_id_from_xml(self, xml_path: Path) -> Optional[RomIdInfo]:
        """
        Extract ROM ID information from an XML definition file

        Args:
            xml_path: Path to XML definition file

        Returns:
            RomIdInfo object or None if parsing fails
        """
        try:
            tree = etree.parse(str(xml_path))
            root = tree.getroot()

            # Find romid element
            romid_elem = root.find('.//romid')
            if romid_elem is None:
                return None

            def get_text(tag: str, default: str = "") -> str:
                elem = romid_elem.find(tag)
                return elem.text.strip() if elem is not None and elem.text else default

            xmlid = get_text('xmlid')
            internalidaddress = get_text('internalidaddress')
            internalidstring = get_text('internalidstring')

            # Must have these essential fields
            if not xmlid or not internalidaddress or not internalidstring:
                return None

            return RomIdInfo(
                xml_path=xml_path,
                xmlid=xmlid,
                internalidaddress=internalidaddress,
                internalidstring=internalidstring,
                make=get_text('make'),
                model=get_text('model')
            )
        except Exception as e:
            print(f"Error parsing XML {xml_path}: {e}")
            return None

    def detect_rom_id(self, rom_path: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Detect ROM ID from a binary file by trying all known definitions

        Args:
            rom_path: Path to ROM binary file

        Returns:
            Tuple of (rom_id_string, xml_path) if match found, (None, None) otherwise
        """
        rom_file = Path(rom_path)
        if not rom_file.exists():
            raise FileNotFoundError(f"ROM file not found: {rom_path}")

        # Load ROM data
        with open(rom_file, 'rb') as f:
            rom_data = f.read()

        # Try each definition
        for rom_info in self.rom_definitions:
            try:
                address = rom_info.internal_id_address_int
                expected_id = rom_info.internalidstring
                id_length = len(expected_id)

                # Check if address is valid for this ROM
                if address + id_length > len(rom_data):
                    continue

                # Read ID from ROM
                actual_id = rom_data[address:address + id_length].decode('ascii', errors='ignore')

                # Check if it matches
                if actual_id == expected_id:
                    return (actual_id, str(rom_info.xml_path))
            except Exception as e:
                print(f"Error checking ROM ID for {rom_info.xmlid}: {e}")
                continue

        return (None, None)

    def find_definition_by_id(self, rom_id: str) -> Optional[str]:
        """
        Find XML definition file by ROM ID string

        Args:
            rom_id: ROM ID string (e.g., "LF9VEB")

        Returns:
            Path to XML definition file or None if not found
        """
        for rom_info in self.rom_definitions:
            if rom_info.xmlid == rom_id or rom_info.internalidstring == rom_id:
                return str(rom_info.xml_path)
        return None

    def get_all_definitions(self) -> List[RomIdInfo]:
        """
        Get list of all available ROM definitions

        Returns:
            List of RomIdInfo objects
        """
        return self.rom_definitions

    def get_definitions_summary(self) -> List[Dict[str, str]]:
        """
        Get summary of all available definitions for display

        Returns:
            List of dictionaries with ROM info
        """
        return [
            {
                'xmlid': info.xmlid,
                'make': info.make,
                'model': info.model,
                'internalid': info.internalidstring,
                'xml_file': info.xml_path.name
            }
            for info in self.rom_definitions
        ]
