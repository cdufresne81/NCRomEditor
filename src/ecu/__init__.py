"""
ECU Patch & XML Definition Tools

Provides SH-2 instruction matching, cross-calibration patch generation,
and XML definition relocation for Mazda NC Miata ROM calibrations.
"""

from .patch_generator import generate_patch, PatchGenResult
from .sh2_match import SH2Matcher, mask_sh2_instructions
from .definition_relocator import DataMatcher, DefinitionRelocator, DefinitionGenResult

__all__ = [
    # Patch Generator
    "generate_patch",
    "PatchGenResult",
    # SH-2 Matching
    "SH2Matcher",
    "mask_sh2_instructions",
    # Definition Relocator
    "DataMatcher",
    "DefinitionRelocator",
    "DefinitionGenResult",
]
