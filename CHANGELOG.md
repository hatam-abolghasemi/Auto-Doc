# Changelog

All notable changes to this project are documented here. Versions follow [Semantic Versioning](https://semver.org/).
Each heading is `## [X.Y.Z] - YYYY-MM-DD — Short description`; the release workflow uses it as the GitHub release title (`vX.Y.Z — Short description`) and the section below it as the notes.

## [1.0.0] - 2026-11-11 — Google Sheets export

First stable release.

### Discovery and collection
- Discovers machines from a list of subnets, with no inventory file to maintain; grouping comes from hostnames.
- Resolves each machine's real static IP (netplan, then default route) when it answers on several.
- Collects OS, CPU, memory, storage (LVM/Ceph/NFS-aware), network, installed tools and Docker containers over plain SSH and shell. Targets need no Python and no agent, and are never modified.
- Writes one flat, sorted JSON file per component to `outputs/`, plus a subnet-based IP inventory.

### Grafana
- `docker-compose.yml` serves `outputs/` through the bundled `json-exposer`, and `dashboard.json` is a ready-made dashboard for the Infinity datasource.

### Google Sheets export
- New `sheets` play builds `outputs/auto-doc.xlsx`: Overview, Groups, Machines, Storage, Network, IP Map, Subnets, Services, Service Details and Containers.
- One row per machine in Machines (OS, CPU, memory merged), one-to-many data in linked tabs; names, groups, counts and subnets jump to the related rows.
- Value-based coloring: OS versions, capacity shading, running/stopped/not-on-boot services, down NICs, read-only disks, IP conflicts, subnet utilization.
- Publishes to the same Google Sheet every run through a service account, with settings in a gitignored `secrets/sheets.yaml` and optional HTTPS proxy support. Setup guide: `docs/google-sheets.md`.

### Project
- CI checks the playbook and scripts, and builds the sample workbook on every push.
- Releases attach the workbook built from `examples/outputs/`.

[1.0.0]: https://github.com/hatam-abolghasemi/auto-doc/releases/tag/v1.0.0
