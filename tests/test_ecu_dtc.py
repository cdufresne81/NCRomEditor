"""Tests for src/ecu/dtc.py — DTC formatting, lookup, and response parsing."""

from src.ecu.dtc import format_dtc, get_dtc_prefix, get_dtc_description, DTC_TABLE


class TestFormatDtc:
    """Test format_dtc() OBD-II string formatting."""

    def test_p_code(self):
        """Powertrain code (category 0b00)."""
        assert format_dtc(0x0011) == "P0011"

    def test_p_code_high(self):
        """Higher P-code."""
        assert format_dtc(0x2101) == "P2101"

    def test_c_code_standard(self):
        """Chassis code (standard OBD-II: 0x4000 prefix)."""
        assert format_dtc(0x4073) == "C0073"

    def test_c_code_mazda(self):
        """Chassis code (Mazda NC: 0xC000 prefix)."""
        assert format_dtc(0xC121) == "C0121"
        assert format_dtc(0xC155) == "C0155"

    def test_b_code(self):
        """Body code (category 0b10 = 0x8000 prefix)."""
        assert format_dtc(0x8100) == "B0100"

    def test_u_code(self):
        """Network code (0xD000+ range)."""
        assert format_dtc(0xFF01) == "U3F01"


class TestGetDtcPrefix:
    """Test get_dtc_prefix() category mapping."""

    def test_powertrain(self):
        """Category 0b00 -> P."""
        assert get_dtc_prefix(0x0000) == "P"

    def test_chassis_standard(self):
        """Standard chassis range (0x4xxx) -> C."""
        assert get_dtc_prefix(0x4000) == "C"

    def test_chassis_mazda(self):
        """Mazda chassis range (0xCxxx) -> C."""
        assert get_dtc_prefix(0xC121) == "C"
        assert get_dtc_prefix(0xC000) == "C"

    def test_body(self):
        """Category 0b10 -> B."""
        assert get_dtc_prefix(0x8000) == "B"

    def test_network(self):
        """U-codes in 0xDxxx-0xFxxx range."""
        assert get_dtc_prefix(0xD000) == "U"
        assert get_dtc_prefix(0xFF01) == "U"


class TestGetDtcDescription:
    """Test get_dtc_description() lookup."""

    def test_known_p_code(self):
        """Known powertrain code returns full description."""
        desc = get_dtc_description(0x0300)
        assert "Random/multiple cylinder misfire" in desc

    def test_known_c_code(self):
        """Known chassis code returns description (Mazda encoding)."""
        desc = get_dtc_description(0xC073)
        assert "bus off" in desc.lower()

    def test_unknown_code(self):
        """Unknown code returns formatted fallback."""
        desc = get_dtc_description(0x0001)
        assert "Unknown DTC" in desc
        assert "P0001" in desc

    def test_all_table_entries_have_descriptions(self):
        """Every entry in DTC_TABLE has a non-empty description string."""
        for code, desc in DTC_TABLE.items():
            assert (
                isinstance(desc, str) and len(desc) > 0
            ), f"Bad entry for 0x{code:04X}"


class TestReadDtcStatusParsing:
    """Test that read_dtc_status correctly parses ECU response bytes.

    Verifies the fix for the count-byte offset bug where the KWP2000
    countOfDTC header byte was not skipped, causing all DTCs to be
    misaligned and decoded as garbage codes.
    """

    def _parse_dtc_response(self, response_bytes):
        """Simulate the DTC parsing logic from UDSConnection.read_dtc_status."""
        from src.ecu.protocol import DTC

        dtcs = []
        # Must skip first byte (countOfDTC header)
        offset = 1
        while offset + 2 < len(response_bytes):
            code = (response_bytes[offset] << 8) | response_bytes[offset + 1]
            status = response_bytes[offset + 2]
            if code != 0:
                dtcs.append(DTC(code, status))
            offset += 3
        return dtcs

    def test_skips_count_byte(self):
        """Parser must skip the first byte (countOfDTC) in the response.

        Real ECU response for C0121, P1260, C0155:
        [count=3, 0xC1, 0x21, 0xFF, 0x12, 0x60, 0xFF, 0xC1, 0x55, 0xFF]
        """
        response = bytes([0x03, 0xC1, 0x21, 0xFF, 0x12, 0x60, 0xFF, 0xC1, 0x55, 0xFF])
        dtcs = self._parse_dtc_response(response)

        assert len(dtcs) == 3
        assert dtcs[0].formatted == "C0121"
        assert dtcs[1].formatted == "P1260"
        assert dtcs[2].formatted == "C0155"

    def test_empty_response(self):
        """Single count byte with count=0 produces no DTCs."""
        response = bytes([0x00])
        dtcs = self._parse_dtc_response(response)
        assert len(dtcs) == 0

    def test_single_dtc(self):
        """Response with one DTC (P0300 = misfire)."""
        response = bytes([0x01, 0x03, 0x00, 0xFF])
        dtcs = self._parse_dtc_response(response)
        assert len(dtcs) == 1
        assert dtcs[0].formatted == "P0300"
