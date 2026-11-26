# Changelog

All notable changes to this project are documented here. Versions follow [Semantic Versioning](https://semver.org/).
Each heading is `## [X.Y.Z] - YYYY-MM-DD — Short description`; the release workflow uses it as the GitHub release title (`vX.Y.Z — Short description`) and the section below it as the notes.

## [1.1.0] - 2026-11-26 — Datacenter-aware inventory

### Datacenters and subnets
- New `subnets.yaml` maps each CIDR to a datacenter and a subnet group. Every machine gets `target_dc` and `target_subnet_group` (most specific CIDR wins, `unknown` when nothing matches) in `hosts.yaml` and every output JSON file, including per-subnet columns in `ip-inventory.json`.
- The same file is now the scan list: each CIDR is expanded into /24s; `scan: false` keeps an entry for labelling only. The `subnets` var in `main.yaml` is now computed from it, and `-e subnets=...` still overrides it.

### Discovery
- One shared time budget per host (`discovery_ssh_timeout`, default 120s) across all user+key attempts, and a configurable `ConnectTimeout` (`discovery_ssh_connect_timeout`, default 20s).
- Hosts that fail for a non-auth reason are retried (`discovery_ssh_retries`, `discovery_ssh_retry_delay`, `discovery_ssh_retry_connect_timeout`); auth refusals are not.
- Every private key in `discovery_ssh_key_dir` (default `~/.ssh`) is tried, each offered on its own with `IdentitiesOnly=yes` so many keys no longer trip `MaxAuthTries`.
- New `outputs/.discovery_failures.log` and `outputs/.discovery_retries.log` say which hosts were dropped or flaky, and why.
- Optional `discovery_ssh_bypass_proxy` adds `-o ProxyCommand=none`, for control nodes where a global `ProxyCommand` (e.g. SSSD) stalls SSH.
- Probing concurrency raised from 50 to 200; `ansible.cfg` sets `forks = 100`.

### Collection
- `tools` checks every tool in one SSH round-trip per host instead of one per tool.

### Google Sheets export
- Machines gains DC and Subnet Group columns, colored per datacenter, and is listed in IP order with a divider at every /24.
- Groups gains DC and Subnet Groups mix columns.
- Workbook font is now Calibri.

### Grafana
- Dashboard tables show `target_dc` and `target_subnet_group` right after `target_group`.

### Project
- Sample data in `examples/outputs/` carries the new fields; `subnets.yaml` ships with example ranges.

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

[1.1.0]: https://github.com/hatam-abolghasemi/auto-doc/releases/tag/v1.1.0
[1.0.0]: https://github.com/hatam-abolghasemi/auto-doc/releases/tag/v1.0.0
