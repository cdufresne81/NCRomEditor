# Anchor-Based Table Address Relocation

## Overview

Each NC MX-5 ROM contains ~850 calibration tables at specific addresses. Different
calibrations (LF9VEB, LF5AEG, LFNPEA, etc.) contain the same tables but at different
addresses. To generate an XML metadata definition for a new calibration, we need to
find where each table landed in the target ROM.

This document describes the **anchor relocation** approach: a set of byte signatures
that are invariant across all known calibrations within a generation. These anchors
are found by searching the target ROM, giving us known address deltas at ~20 points.
All other table addresses are interpolated from the nearest anchors and verified.

## Why Anchors Work

Within a generation (NC1 or NC2), all calibrations share the same firmware codebase.
The tables are laid out in the same order, but the linker places them at different
base offsets. The offset isn't uniform — it varies across ROM regions due to
inserted/removed code between sections. However:

1. **Table order is preserved** — tables always appear in the same sequence
2. **Delta changes are small** — adjacent tables typically differ by 0-64 bytes in delta
3. **Certain values are invariant** — conversion constants, axis breakpoints, and
   structural parameters are identical across all calibrations

The invariant values serve as anchors: their 32-byte signature can be found in any
ROM of the same generation, giving an exact address match.

## Methodology

### Anchor Selection Criteria

An anchor must satisfy ALL of the following:

1. **Unique signature**: The 32 bytes at the anchor address appear exactly once in
   every ROM of the generation (no false positives)
2. **Universal presence**: The table exists in every known calibration
3. **Cross-ROM findable**: The reference ROM's signature finds the correct address
   in every other ROM (not just unique within each ROM — the actual bytes must be
   identical across calibrations)
4. **Verified against ground truth**: The found address matches the RomDrop-verified
   address for all 103 calibrations with known definitions

### Verification Dataset

- **NC2**: 64 calibrations verified (LF9VEB reference + 63 others)
- **NC1**: 39 calibrations verified (LFG1EK reference + 38 others)
- **Cross-validation**: LFNPEA (not in RomDrop database) verified independently
- **Source**: RomDrop metadata definitions provide ground-truth table addresses

### Relocation Algorithm

1. **Find anchors**: Search the target ROM for each 32-byte signature. Each match
   gives us `target_addr = match_position`, and the delta is
   `delta = target_addr - ref_addr`.

2. **Interpolate**: For each table address in the reference definition:
   - Find the two nearest anchors (one before, one after by reference address)
   - If both anchors have the same delta → apply that delta
   - If deltas differ → linear interpolation weighted by distance, rounded to
     nearest 4-byte boundary
   - If only one anchor found → use that delta

3. **Verify**: Read 4-16 bytes at the estimated target address and compare against
   the reference ROM. If verification fails, flag as low-confidence.

4. **Fallback**: For addresses where no nearby anchor exists or verification fails,
   fall back to the byte-context matching algorithm (Phase 1-4).

## NC2 Anchors

**Reference calibration**: LF9VEB
**Verified against**: 64 NC2 calibrations (63/63 cross-ROM + LFNPEA)

| # | Ref Address | Signature (32 bytes hex) | Table Name |
|---|-------------|--------------------------|------------|
| 1 | `0xBA86C` | `41194bc7411c08314123db23412b1eb8412da5e3412e872b4131ced9413276c9` | VCT Error - CKP to CMP Synchronizing Offset |
| 2 | `0xBB0D0` | `412800004180000040a00000428c000042bd00004120000042bd000040000000` | TP Closed - Default |
| 3 | `0xBB840` | `456a600044bb800043fa000042bb800045502000447a000044bb800044fa0000` | IMTV Short Runner Activation A - Max RPM Threshold |
| 4 | `0xBF4F4` | `428c000042a0000042b4000042c800003fb333333f9b43963f8df3b63f800000` | AFS Scaling - Barometric Multiplier |
| 5 | `0xBF9E0` | `00a200a200a200a200a200a200a200a24257b85242776666428b8000429b570a` | Low Speed Fan Enable - ECT Threshold |
| 6 | `0xC012C` | `41340000000000004479c0003f9f5c29000000004070a3d7419666664070a3d7` | Tip-In Retard First Gear |
| 7 | `0xC9EA4` | `456a600042bb8000454b200042bb800043fa0000447a000044bb800044fa0000` | IMRC Cold Exit - RPM Threshold |
| 8 | `0xCE25C` | `457a000042bb8000459c4000447a0000459c400042bb80004479c00040a00000` | Spark Enrichment - RPM Threshold |
| 9 | `0xCFBE8` | `00000000000000000000000000000000411dc28f4120000042480000c1580000` | Spark Final Trim - Cylinder 1 |
| 10 | `0xD4A8C` | `000000000000000042c8000040a00000459c400042bb800000080c000000ffff` | Spark Retard Limit - LC Activated |
| 11 | `0xDA4CC` | `40d00000413000003d4ccccd3ca3d70a3cf5c28f3d4ccccd3ca3d70ac2200000` | Tip-In Retard From Stop |
| 12 | `0xF44C0` | `42b40000412db22d0000000040cae9790000000041c80000412db22d41c80000` | TP Delta - Fault Threshold |

### NC2 Coverage Map

```
ROM Address:  0x00000 -------- 0xBA86C ============================================ 0xF44C0 -- 0xFFFFF
Anchors:                         1  2  3      4  5   6          7      8  9    10    11        12
Spacing:                        |2K|8K|      17K|2K| 7K|       28K|   12K|14K| 17K| 30K|     42K|
```

The main calibration region (0xB8000-0xF5000) has 12 anchors with typical spacing
of 8-30KB. The patch/DTC regions before 0xBA000 have no reliable anchors (calibration
data varies) but contain few tables.

### Supplementary NC2 Anchors (Partial Coverage)

These anchors work on most but not all NC2 ROMs. Use as fallback when primary
anchors have large gaps:

| Ref Address | Coverage | Table Name |
|-------------|----------|------------|
| `0x46DC6` | 45/63 | [Patch] DFCO Disable |
| `0x9699A` | 54/63 | [Patch] Immobilizer Bypass - PARTIAL |
| `0xC4C40` | 58/63 | Speed Limiter - RPM Activation Threshold |
| `0xCBD80` | 53/63 | Injector Scaling - Global Multiplier |
| `0xDB758` | 54/63 | IAT Scaling - Voltage to IAT |

## NC1 Anchors

**Reference calibration**: LFG1EK
**Verified against**: 39 NC1 calibrations (38/38 cross-ROM)

| # | Ref Address | Signature (32 bytes hex) | Table Name |
|---|-------------|--------------------------|------------|
| 1 | `0x45A6E` | `8f02ff9da045fefad0676000c810002970ff600b88018f13f4e8d363f338f435` | [Patch] DFCO Disable |
| 2 | `0x91FC2` | `8f080009b1c70009e27f94182e204f26a3ef6ef6b1dd000992112e20b3e9e401` | [Patch] Immobilizer Bypass - PARTIAL |
| 3 | `0xB8108` | `3d71a9fb3ebdf3b63f2f1a9f3f7ef9db3fa78d4f3fcf7ced3ff78d4f400fbe76` | IAT Scaling - Voltage to IAT |
| 4 | `0xBCA68` | `3f8000003ecccccd3ecccccd3ecccccd3ecccccd3e99999a3e99999a3e99999a` | KS Magnitude EMA Weighting - Mult B |
| 5 | `0xC49CC` | `3c800a7c3c800a7c3c800a7c3da0029f3dc000003dc000003dc000003e100150` | OL Decel Transition - Load Threshold |
| 6 | `0xC8D34` | `456a600042bb8000454b200042bb800043fa0000447a000044bb800044fa0000` | IMRC Cold Exit - RPM Threshold |
| 7 | `0xCCF89` | `28ffff4479c00040a000004479c00040a000004479c0003d4ccccd45fa000042` | Power Enleanment Reset Delay |
| 8 | `0xD2E04` | `00000000000000000000000042c8000040a00000459c400042bb800000080c00` | Spark Retard Rate - LC Activated |
| 9 | `0xD88F8` | `40d00000413000003d4ccccd3ca3d70a3cf5c28f3d4ccccd3ca3d70ac2200000` | Tip-In Retard From Stop |
| 10 | `0xDD713` | `0101010101010101010101010101010101010101010101010101010101010103` | P0011 - CMP timing over-advanced |
| 11 | `0xF44B0` | `42b40000412db22d0000000040cae9790000000041c80000412db22d41c80000` | TP Delta - Fault Threshold |

## Address Index

The file `examples/metadata/address_index.csv` contains the complete ground-truth
address mapping for 888 tables across 103 calibrations (from RomDrop definitions).
This serves as both a validation dataset and a direct lookup for known calibrations.

## Limitations

1. **Pre-0xBA000 region**: Few invariant anchors exist in the patch and early
   calibration region. Tables here (Flex Fuel, some DTCs) may need byte-context
   matching fallback.

2. **New table types**: If a calibration adds tables not present in the reference
   definition, anchors cannot locate them. This is rare within a generation.

3. **Signature collisions**: While all anchors are verified unique across 103+
   calibrations, a hypothetical future ROM could theoretically produce a false
   positive. The verification step (comparing bytes at the estimated address)
   guards against this.

4. **Cross-generation**: NC1 and NC2 anchors are NOT interchangeable. The firmware
   is fundamentally different between generations. Always detect the generation
   first (via `detect_vehicle_generation()`) before selecting the anchor set.
