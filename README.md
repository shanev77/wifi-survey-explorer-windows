# Wi-Fi Survey Explorer (Windows)

Version 1.1.1. Python / PySide6 desktop application for analysing recorded Wi-Fi surveys; it does not scan networks. Copyright 2026 Shane van Ingen.

* Features

Empty startup; multi-file CSV import and review; SQLite projects; searchable AP identities; combined frequency, band, channel, security, names, signal, source/session and date filters; hover details; double-click AP map focus; automatic per-AP RSSI surfaces; approximate RSSI location estimates; explicit offline map packages; CSV, GeoJSON, GeoTIFF and map-image export. The About menu includes the supplied author photo.

* Run and build

Use Python 3.14 x64 (the tested version). Create `.venv`, install `requirements.txt`, then run `python main.py` in that environment. Run `powershell -ExecutionPolicy Bypass -File build.ps1` for a folder distribution. Add `-Standalone` for one EXE, or `-Both` for both formats. Target machines do not need Python or Node.js.

The standalone EXE extracts its resources to a temporary directory when started. The folder EXE needs its entire `_internal` directory. Neither format loads surveys automatically.

* Structure

- `survey_explorer/importing.py`: parsing, validation, source provenance and deduplication keys.
- `storage.py`: transactional SQLite projects and atomic save.
- `filtering.py`: consistent filters for all views and analysis.
- `analysis.py`: metric aggregation, conservative IDW surfaces and RSSI estimators.
- `maps.py`: localhost frontend server and explicit offline map packages.
- `exporting.py`: CSV, GeoJSON and georeferenced raster output.
- `ui.py`: desktop widgets, worker scheduling and WebChannel bridge.
- `assets/`: bundled MapLibre/WebChannel frontend, app.js, CSS, icons and author photo.
- `tests/`: import, storage, estimation, interpolation, filtering and offline-server regression checks.

Run `python -m pytest tests -q`. Private-survey tests skip when the original files are unavailable. The `verify_*.py` integration scripts require a locally generated demo and its offline maps.

*** Data and interpretation

Private CSVs, map caches, screenshots, saved projects, binaries and machine-specific configuration are intentionally absent. To build a private demo, place your own `wifi-survey*.csv` files in this folder and run `scripts/make_demo.py`. Do not commit those files. `scripts/prepare_maps.py` downloads the local demo's map coverage and reveals its approximate area to OpenFreeMap.

Map provider: OpenFreeMap Liberty. No credentials required for the default provider. Local frontend libraries do not use runtime CDNs. Provider terms and attribution apply; download limits are enforced. Offline cache is stored separately under `%LOCALAPPDATA%/WiFiSurveyExplorer/maps.sqlite`.

Heatmaps describe measured/interpolated reception, not a known transmitter position. Sparse or straight-line samples may not support a surface. The baseline and experimental estimates display approximate uncertainty; synthetic tests do not establish real-world accuracy.

Original copyright is retained; third-party terms are in `THIRD_PARTY_NOTICES.md` and `third-party-licenses/`. No additional open-source licence has been selected for the original application code.
