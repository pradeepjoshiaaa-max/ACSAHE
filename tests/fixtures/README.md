# Test Fixtures

This directory stores reusable test data grouped by purpose.

## Layout

- `excel/`: Source workbook fixtures (`.xlsm`) used by slow integration tests that open Excel through xlwings.
- `json/`: Portable JSON inputs used by fast integration/e2e tests that avoid Excel UI.
- `golden/`: Expected outputs used for regression checks (for example, precomputed 3D surface points).

## Current files

- `excel/01_box_girder.xlsm`: Box-girder cross section (ACI 318-19 assumptions).
- `excel/02_circular_pile.xlsm`: Circular pile with spiral reinforcement.
- `excel/03_box_girder_custom_steels.xlsm`: Box-girder case with custom steel materials.
- `json/01_box_girder.json`: Portable input equivalent used by e2e and parity checks.
- `json/03_box_girder_custom_steels.json`: Portable input equivalent with custom steels.
- `golden/01_box_girder_e2e_3d_surface_points.json`: Golden e2e surface points for regression.

## Contributor notes

- Prefer adding new files over modifying existing fixtures if historical regression behavior must be preserved.
- Use deterministic fixture data (no external links, volatile formulas, or machine-specific dependencies).
- Keep naming predictable with numeric prefixes (`04_...`) and document every new fixture here.
