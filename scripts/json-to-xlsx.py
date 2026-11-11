#!/usr/bin/env python3
"""Build the Auto-Doc infrastructure workbook from outputs/*.json.

A machine is identified by (target_name, target_ip, target_group) everywhere.
One-to-one facts (OS, CPU, memory) are merged into Machines; one-to-many facts
(disks, NICs, services, containers) get their own sheets, linked back to it.

Writes two files:
  auto-doc.xlsx         styled workbook (links work locally in Excel/LibreOffice)
  auto-doc.links.json   cross-sheet links; xlsx-to-sheets.py re-creates them as
                        HYPERLINK formulas after the Google Sheets upload, since
                        internal xlsx links do not survive Drive's conversion.

Usage:
    python3 scripts/json-to-xlsx.py --input outputs --output outputs/auto-doc.xlsx
"""

import argparse
import ipaddress
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

FONT_NAME = "Times New Roman"
KEY_FIELDS = ("target_name", "target_ip", "target_group")
PLACEHOLDERS = {"", "-", "none", "unknown", "n/a", "null", "None"}

# Section / sheet colors (dark: header fill with white text).
COLOR = {
    "identity": "24292F", "os": "1F4E79", "cpu": "8B2E2A", "memory": "5B3A87",
    "storage": "8A5A00", "network": "1B6B5A", "services": "2E6B30",
    "containers": "0B5394", "groups": "37474F", "ip": "455A64",
}
# Light categorical tints (OS versions, groups on the IP map, disk types...).
PASTELS = [
    "DBEAFE", "FCE7F3", "DCFCE7", "FEF3C7", "EDE9FE", "CCFBF1", "FFE4E6", "E0F2FE",
    "FEF9C3", "F3E8FF", "D1FAE5", "FFEDD5", "E0E7FF", "FAE8FF", "ECFCCB", "F5F5F4",
]
SEQUENTIAL = ["F4F8FC", "DCE9F5", "BFD7EE", "9CC2E5", "74A9D8"]   # small -> large
HEAT = ["E6F4EA", "F1F8D8", "FFF4CE", "FFE0B2", "FFCDD2"]         # utilization
GOOD = ("D4EDDA", "1A7F37")
BAD = ("F8D7DA", "CF222E")
WARN = ("FFF3CD", "8A5A00")
MUTED = "9AA0A6"
LINK = "0B57D0"

THIN = Side(style="thin", color="D0D7DE")
GROUP_EDGE = Side(style="medium", color="8C959F")


# --------------------------------------------------------------------------- helpers

def font(**kw):
    return Font(name=FONT_NAME, **kw)


def fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)


def clean(value):
    """Strip; placeholders become None so cells stay empty."""
    if value is None:
        return None
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value).strip()
    return None if text in PLACEHOLDERS or text.lower() in PLACEHOLDERS else text


def to_int(value):
    text = clean(value)
    return int(text) if text and re.fullmatch(r"-?\d+", text) else None


def natural(value):
    text = "" if value is None else str(value)
    return [(0, int(t), "") if t.isdigit() else (1, 0, t.lower()) for t in re.split(r"(\d+)", text) if t]


def machine_key(row):
    return tuple(str(row.get(k, "")).strip() for k in KEY_FIELDS)


def machine_sort(key):
    name, ip, group = key
    return (natural(group), natural(name), natural(ip))


def gib(value_bytes):
    return round(value_bytes / 1024 ** 3, 1)


def bucket(value, distinct_sorted, palette):
    """Color by rank among distinct values, so a few distinct sizes still differ."""
    if value is None or not distinct_sorted:
        return None
    if len(distinct_sorted) == 1:
        return palette[len(palette) // 2]
    rank = distinct_sorted.index(value) / (len(distinct_sorted) - 1)
    return palette[min(int(rank * len(palette)), len(palette) - 1)]


def categorical(values):
    """Stable value -> pastel map (sorted naturally)."""
    ordered = sorted({v for v in values if v}, key=natural)
    return {v: PASTELS[i % len(PASTELS)] for i, v in enumerate(ordered)}


def truthy(value):
    return (clean(value) or "").lower() in {"true", "yes", "1", "enabled", "active", "up"}


def load(input_dir, stem):
    path = Path(input_dir) / f"{stem}.json"
    if not path.exists():
        print(f"note: {path.name} missing, its sheet will be empty", file=sys.stderr)
        return []
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        sys.exit(f"{path.name}: expected a JSON array")
    return [r for r in data if isinstance(r, dict)]


# --------------------------------------------------------------------------- sheet writer

class SheetWriter:
    """Thin wrapper: consistent styling, column widths, link bookkeeping."""

    def __init__(self, book, title, color, links):
        self.ws = book.create_sheet(title=title)
        self.ws.sheet_properties.tabColor = color
        self.title = title
        self.color = color
        self.links = links
        self.widths = defaultdict(int)

    def header(self, row, columns, sections=None):
        """columns: list of names. sections: list of (label, color, span) for a band above."""
        if sections:
            col = 1
            for label, color, span in sections:
                cell = self.ws.cell(row=row - 1, column=col, value=label)
                cell.fill = fill(color)
                cell.font = font(bold=True, color="FFFFFF", size=11)
                cell.alignment = Alignment(horizontal="center", vertical="center")
                if span > 1:
                    self.ws.merge_cells(start_row=row - 1, start_column=col,
                                        end_row=row - 1, end_column=col + span - 1)
                for c in range(col, col + span):
                    self.ws.cell(row=row - 1, column=c).border = Border(left=THIN if c == col else None,
                                                                         right=THIN if c == col + span - 1 else None)
                col += span
            self.ws.row_dimensions[row - 1].height = 22
        section_of = []
        for label, color, span in (sections or [(None, self.color, len(columns))]):
            section_of += [color] * span
        for ci, name in enumerate(columns, start=1):
            cell = self.ws.cell(row=row, column=ci, value=name)
            cell.fill = fill(section_of[ci - 1])
            cell.font = font(bold=True, color="FFFFFF")
            cell.alignment = Alignment(vertical="center", wrap_text=False)
            cell.border = Border(bottom=THIN, right=THIN)
            self.widths[ci] = max(self.widths[ci], len(str(name)) + 4)
        self.ws.row_dimensions[row].height = 24

    def put(self, row, col, value, *, bg=None, fg=None, bold=False, italic=False,
            number_format=None, align=None, top_edge=False, band=None):
        cell = self.ws.cell(row=row, column=col, value=value)
        cell.font = font(bold=bold, italic=italic, color=fg)
        if bg or band:
            cell.fill = fill(bg or band)
        if number_format:
            cell.number_format = number_format
        cell.alignment = Alignment(vertical="center",
                                   horizontal=align or ("right" if isinstance(value, (int, float)) else "left"))
        cell.border = Border(top=GROUP_EDGE if top_edge else THIN, bottom=THIN, right=THIN)
        if value is not None:
            shown = f"{value:,.1f}" if isinstance(value, float) else str(value)
            self.widths[col] = max(self.widths[col], round(len(shown) * (1.15 if bold else 1)) + 2)
        return cell

    def link(self, row, col, target_sheet, target_row, target_col, text, **style):
        """Write a cell that jumps to another sheet; remember it for the Google pass."""
        style.setdefault("fg", LINK)
        cell = self.put(row, col, text, **style)
        target = f"{get_column_letter(target_col)}{target_row}"
        cell.hyperlink = f"#'{target_sheet}'!{target}"
        if style["fg"] == LINK:
            cell.font = font(bold=style.get("bold", False), color=LINK, underline="single")
        self.links.append({
            "sheet": self.title, "cell": f"{get_column_letter(col)}{row}",
            "target_sheet": target_sheet, "target_cell": target, "text": str(text),
        })
        return cell

    def finish(self, freeze, filter_row=None, last_row=None, last_col=None, max_width=48, min_width=6):
        for col, width in self.widths.items():
            self.ws.column_dimensions[get_column_letter(col)].width = max(min_width, min(width, max_width))
        self.ws.freeze_panes = freeze
        if filter_row and last_row and last_row > filter_row:
            self.ws.auto_filter.ref = f"A{filter_row}:{get_column_letter(last_col)}{last_row}"


# --------------------------------------------------------------------------- model

def build_model(input_dir):
    raw = {stem: load(input_dir, stem)
           for stem in ("os", "cpu", "memory", "storage", "network", "tools", "docker")}

    one = {stem: {machine_key(r): r for r in raw[stem]} for stem in ("os", "cpu", "memory")}
    many = defaultdict(lambda: defaultdict(list))
    for stem in ("storage", "network", "tools", "docker"):
        for r in raw[stem]:
            many[stem][machine_key(r)].append(r)

    machines = set()
    for stem in raw:
        machines.update(machine_key(r) for r in raw[stem])
    machines = sorted((m for m in machines if m[0]), key=machine_sort)
    return machines, one, many


# --------------------------------------------------------------------------- sheets

def write_machines(book, links, machines, one, many, rows):
    s = SheetWriter(book, "Machines", COLOR["identity"], links)
    sections = [("Identity", COLOR["identity"], 3), ("OS", COLOR["os"], 5), ("CPU", COLOR["cpu"], 4),
                ("Memory", COLOR["memory"], 2), ("Storage", COLOR["storage"], 2),
                ("Network", COLOR["network"], 3), ("Software", COLOR["services"], 2)]
    columns = ["Name", "IP", "Group",
               "OS", "Version", "Codename", "Arch", "Timezone",
               "Physical Cores", "Sockets", "Logical CPUs", "Platform",
               "RAM (GiB)", "Online",
               "Disks", "Disk Total (GiB)",
               "NICs", "Subnets", "Gateway",
               "Services", "Containers"]
    s.header(2, columns, sections)

    os_versions = categorical(f"{clean(one['os'].get(m, {}).get('os_name')) or ''} "
                              f"{clean(one['os'].get(m, {}).get('os_version')) or ''}".strip()
                              for m in machines)
    numeric_cols = defaultdict(list)
    prepared = []
    for m in machines:
        o, c, mem = one["os"].get(m, {}), one["cpu"].get(m, {}), one["memory"].get(m, {})
        disks = many["storage"].get(m, [])
        nics = many["network"].get(m, [])
        disk_total = sum(to_int(d.get("storage_size_bytes")) or 0 for d in disks
                         if clean(d.get("storage_type")) != "network_mount")
        default = next((n for n in nics if truthy(n.get("network_is_default"))), None)
        gateway = clean((default or {}).get("network_gateway")) or next(
            (clean(n.get("network_gateway")) for n in nics if clean(n.get("network_gateway"))), None)
        subnets = sorted({clean(n.get("network_subnet")) for n in nics if clean(n.get("network_subnet"))},
                         key=natural)
        if c:
            vm = truthy(c.get("cpu_is_virtual_machine"))
            vendor = clean(c.get("cpu_virt_hypervisor_vendor"))
            platform = (f"VM ({vendor})" if vendor else "VM") if vm else "Physical"
        else:
            platform = None
        ram_kb = to_int(mem.get("memory_size_kb"))
        p = {
            "key": m, "os": o, "cpu": c, "mem": mem, "platform": platform,
            "os_label": f"{clean(o.get('os_name')) or ''} {clean(o.get('os_version')) or ''}".strip(),
            "phys": to_int(c.get("cpu_physical_cores")), "sockets": to_int(c.get("cpu_sockets")),
            "logical": to_int(c.get("cpu_logical_processors")),
            "ram": round(ram_kb / 1024 ** 2, 1) if ram_kb else None,
            "disks": len(disks), "disk_total": gib(disk_total) if disk_total else None,
            "nics": len(nics), "subnets": ", ".join(subnets), "gateway": gateway,
            "services": len(many["tools"].get(m, [])), "containers": len(many["docker"].get(m, [])),
        }
        for k in ("phys", "logical", "ram", "disk_total"):
            if p[k] is not None:
                numeric_cols[k].append(p[k])
        prepared.append(p)
    scales = {k: sorted(set(v)) for k, v in numeric_cols.items()}

    r = 3
    last_group = None
    for p in prepared:
        m = p["key"]
        rows["machines"][m] = r
        edge = last_group is not None and m[2] != last_group
        last_group = m[2]
        o = p["os"]
        s.put(r, 1, m[0], bold=True, top_edge=edge)
        s.put(r, 2, m[1], top_edge=edge)
        s.link(r, 3, "Groups", rows["groups"].get(m[2], 2), 1, m[2], top_edge=edge)
        tint = os_versions.get(p["os_label"])
        s.put(r, 4, clean(o.get("os_name")), bg=tint, top_edge=edge)
        s.put(r, 5, clean(o.get("os_version")), bg=tint, bold=True, top_edge=edge)
        s.put(r, 6, clean(o.get("os_codename")), top_edge=edge)
        s.put(r, 7, clean(o.get("os_architecture")), top_edge=edge)
        s.put(r, 8, clean(o.get("os_timezone")), top_edge=edge)
        s.put(r, 9, p["phys"], bg=bucket(p["phys"], scales.get("phys", []), SEQUENTIAL), bold=True, top_edge=edge)
        s.put(r, 10, p["sockets"], top_edge=edge)
        s.put(r, 11, p["logical"], bg=bucket(p["logical"], scales.get("logical", []), SEQUENTIAL), top_edge=edge)
        plat = p["platform"]
        s.put(r, 12, plat, bg=("EEF2FF" if plat and plat.startswith("VM") else "FDF2E9") if plat else None,
              top_edge=edge)
        s.put(r, 13, p["ram"], bg=bucket(p["ram"], scales.get("ram", []), SEQUENTIAL),
              number_format="#,##0.0", bold=True, top_edge=edge)
        s.put(r, 14, clean(p["mem"].get("memory_total_online_memory")), top_edge=edge)
        _count_link(s, r, 15, p["disks"], "Storage", rows["storage"].get(m), edge)
        s.put(r, 16, p["disk_total"], bg=bucket(p["disk_total"], scales.get("disk_total", []), SEQUENTIAL),
              number_format="#,##0.0", top_edge=edge)
        _count_link(s, r, 17, p["nics"], "Network", rows["network"].get(m), edge)
        s.put(r, 18, p["subnets"] or None, top_edge=edge)
        s.put(r, 19, p["gateway"], top_edge=edge)
        _count_link(s, r, 20, p["services"], "Services", rows["services"].get(m), edge)
        _count_link(s, r, 21, p["containers"], "Containers", rows["containers"].get(m), edge)
        r += 1

    s.finish(freeze="D3", filter_row=2, last_row=r - 1, last_col=len(columns))
    return prepared


def _count_link(s, r, col, count, sheet, target_row, edge):
    if count and target_row:
        s.link(r, col, sheet, target_row, 1, count, align="right", top_edge=edge)
    else:
        s.put(r, col, None, top_edge=edge)


def write_one_to_many(book, links, title, color, data, machines, rows, row_key, columns, render, sort_key):
    s = SheetWriter(book, title, color, links)
    s.header(2, ["Name", "IP", "Group"] + columns,
             [("Machine", COLOR["identity"], 3), (title, color, len(columns))])
    r = 3
    band = False
    for m in machines:
        items = sorted(data.get(m, []), key=sort_key)
        if not items:
            continue
        band = not band
        rows[row_key][m] = r
        for i, item in enumerate(items):
            first = i == 0
            bg = "F6F8FA" if band else None
            if first:
                s.link(r, 1, "Machines", rows["machines"][m], 1, m[0], bold=True, top_edge=True, band=bg)
            else:
                s.put(r, 1, m[0], fg=MUTED, band=bg)
            s.put(r, 2, m[1], fg=None if first else MUTED, top_edge=first, band=bg)
            s.put(r, 3, m[2], fg=None if first else MUTED, top_edge=first, band=bg)
            for ci, spec in enumerate(render(item, m, r), start=4):
                value, style = spec if isinstance(spec, tuple) else (spec, {})
                style = dict(style)
                link = style.pop("link", None)
                style.setdefault("band", bg)
                if link:
                    s.link(r, ci, *link, value, top_edge=first, **style)
                else:
                    s.put(r, ci, value, top_edge=first, **style)
            r += 1
    s.finish(freeze="D3", filter_row=2, last_row=r - 1, last_col=3 + len(columns))
    return s


def write_storage(book, links, machines, many, rows):
    types = categorical(clean(d.get("storage_type")) for ds in many["storage"].values() for d in ds)
    sizes = sorted({gib(to_int(d.get("storage_size_bytes")))
                    for ds in many["storage"].values() for d in ds if to_int(d.get("storage_size_bytes"))})

    def render(d, m, r):
        size = to_int(d.get("storage_size_bytes"))
        size = gib(size) if size else None
        ro = truthy(d.get("storage_read_only"))
        return [
            (clean(d.get("storage_mountpoint")), {"bold": True}),
            clean(d.get("storage_device_name")),
            clean(d.get("storage_fstype")),
            (size, {"number_format": "#,##0.0", "bg": bucket(size, sizes, SEQUENTIAL)}),
            (clean(d.get("storage_type")), {"bg": types.get(clean(d.get("storage_type")))}),
            clean(d.get("storage_model")),
            clean(d.get("storage_vendor")),
            clean(d.get("storage_transport")),
            ("read-only", {"bg": BAD[0], "fg": BAD[1], "bold": True}) if ro else None,
        ]

    write_one_to_many(book, links, "Storage", COLOR["storage"], many["storage"], machines, rows, "storage",
                      ["Mountpoint", "Device", "FS", "Size (GiB)", "Type", "Model", "Vendor", "Transport",
                       "Read-only"],
                      render, lambda d: natural(d.get("storage_mountpoint")))


def write_network(book, links, machines, many, rows, ipmap_cols):
    def render(n, m, r):
        up = (clean(n.get("network_state")) or "").lower()
        subnet = clean(n.get("network_subnet"))
        target = ipmap_cols.get(_slash24(clean(n.get("network_ip"))))
        return [
            (clean(n.get("network_device")), {"bold": True}),
            clean(n.get("network_ip")),
            (subnet, {"link": ("IP Map", 1, target)}) if subnet and target else subnet,
            clean(n.get("network_gateway")),
            clean(n.get("network_mac")),
            to_int(n.get("network_mtu")),
            (up or None, {"bg": GOOD[0], "fg": GOOD[1], "bold": True} if up == "up"
             else {"bg": BAD[0], "fg": BAD[1], "bold": True} if up else {}),
            ("default", {"bold": True}) if truthy(n.get("network_is_default")) else None,
        ]

    write_one_to_many(book, links, "Network", COLOR["network"], many["network"], machines, rows, "network",
                      ["Device", "IP Address", "Subnet", "Gateway", "MAC", "MTU", "State", "Default Route"],
                      render,
                      lambda n: (not truthy(n.get("network_is_default")), natural(n.get("network_device"))))


def write_service_details(book, links, machines, many, rows, matrix_cols):
    def render(t, m, r):
        rows["service_detail"][(m, clean(t.get("tool_name")))] = r
        status = (clean(t.get("tool_status")) or "").lower()
        enabled = (clean(t.get("tool_enabled")) or "").lower()
        col = matrix_cols.get(clean(t.get("tool_name")))
        name = clean(t.get("tool_name"))
        return [
            (name, {"bold": True, "link": ("Services", rows["services"].get(m), col)}) if col else name,
            clean(t.get("tool_version")),
            (status or None, _status_style(status)),
            (enabled or None, {"fg": WARN[1], "bg": WARN[0]} if enabled and enabled not in ("enabled", "true")
             else {}),
            clean(t.get("tool_ports")),
            clean(t.get("tool_manager")),
            clean(t.get("tool_path")),
        ]

    write_one_to_many(book, links, "Service Details", COLOR["services"], many["tools"], machines, rows,
                      "service_details",
                      ["Service", "Version", "Status", "Boot", "Ports", "Manager", "Path"],
                      render, lambda t: natural(t.get("tool_name")))


def _status_style(status):
    if status in ("active", "running"):
        return {"bg": GOOD[0], "fg": GOOD[1], "bold": True}
    if status in ("inactive", "failed", "dead", "stopped", "exited"):
        return {"bg": BAD[0], "fg": BAD[1], "bold": True}
    return {}


def write_containers(book, links, machines, many, rows):
    images = categorical((clean(c.get("docker_image")) or "").split(":")[0]
                         for cs in many["docker"].values() for c in cs)

    def render(c, m, r):
        image = clean(c.get("docker_image"))
        return [
            (clean(c.get("docker_container_name")), {"bold": True}),
            (image, {"bg": images.get((image or "").split(":")[0])}),
            clean(c.get("docker_ports")),
            clean(c.get("docker_networks")),
            clean(c.get("docker_mount_mappings")),
        ]

    write_one_to_many(book, links, "Containers", COLOR["containers"], many["docker"], machines, rows, "containers",
                      ["Container", "Image", "Ports", "Networks", "Mounts"],
                      render, lambda c: natural(c.get("docker_container_name")))


def services_layout(machines, many):
    counts = Counter(clean(t.get("tool_name")) for ts in many["tools"].values() for t in ts if clean(t.get("tool_name")))
    tools = sorted(counts, key=lambda t: (-counts[t], natural(t)))
    return tools, {t: 4 + i for i, t in enumerate(tools)}


def write_services(book, links, machines, many, rows, tools, matrix_cols):
    """Matrix: what is installed where. Blank = not installed."""
    s = SheetWriter(book, "Services", COLOR["services"], links)
    s.header(2, ["Name", "IP", "Group"] + tools,
             [("Machine", COLOR["identity"], 3), ("Installed services (version)", COLOR["services"],
                                                  max(len(tools), 1))])
    r = 3
    last_group = None
    for m in machines:
        installed = {clean(t.get("tool_name")): t for t in many["tools"].get(m, []) if clean(t.get("tool_name"))}
        if not installed:
            continue
        edge = last_group is not None and m[2] != last_group
        last_group = m[2]
        rows["services"][m] = r
        s.link(r, 1, "Machines", rows["machines"][m], 1, m[0], bold=True, top_edge=edge)
        s.put(r, 2, m[1], top_edge=edge)
        s.put(r, 3, m[2], top_edge=edge)
        for tool, col in matrix_cols.items():
            t = installed.get(tool)
            if not t:
                s.put(r, col, None, top_edge=edge)
                continue
            version = clean(t.get("tool_version")) or "installed"
            style = _status_style((clean(t.get("tool_status")) or "").lower())
            style = {"bg": style.get("bg", "F6F8FA"), "fg": style.get("fg", "24292F")}
            enabled = (clean(t.get("tool_enabled")) or "").lower()
            if style["bg"] == GOOD[0] and enabled and enabled not in ("enabled", "true"):
                style = {"bg": WARN[0], "fg": WARN[1]}  # running but not enabled at boot
            # Link target is filled in after Service Details is written (row numbers known then).
            s.put(r, col, version, align="center", top_edge=edge, **style)
            rows["matrix_cells"].append((r, col, m, tool))
        r += 1
    for col in matrix_cols.values():
        s.widths[col] = max(s.widths[col], 10)
    s.finish(freeze="D3", filter_row=2, last_row=r - 1, last_col=3 + len(tools), max_width=22)
    return s


def link_matrix(svc_sheet, rows):
    for r, col, m, tool in rows["matrix_cells"]:
        target = rows["service_detail"].get((m, tool))
        if not target:
            continue
        cell = svc_sheet.ws.cell(row=r, column=col)
        style = {"bg": cell.fill.fgColor.rgb[-6:], "fg": cell.font.color.rgb[-6:] if cell.font.color else None}
        svc_sheet.link(r, col, "Service Details", target, 4, cell.value, align="center", **style)


# --------------------------------------------------------------------------- IP map / subnets

def _slash24(ip):
    try:
        return str(ipaddress.ip_network(f"{ip}/24", strict=False))
    except (ValueError, TypeError):
        return None


VIRTUAL_NICS = ("docker", "br-", "cni", "flannel", "cali", "veth", "kube", "virbr", "tun", "tap", "wg",
                "vxlan", "lxc", "podman", "cilium", "weave")


def ip_layout(machines, many):
    """Columns = /24s holding a machine's target_ip, plus backend /24s that real NICs
    of 2+ machines use. Container/overlay interfaces are ignored: per-host bridge
    IPs (docker0 172.17.0.1, cni0...) would otherwise flood the map with noise."""
    owners = defaultdict(set)      # ip -> {machine}
    nets_with = defaultdict(set)   # /24 -> {machine}
    gw_candidates = set()
    for m in machines:
        owners[m[1]].add(m)
        if _slash24(m[1]):
            nets_with[_slash24(m[1])].add(m)
        for n in many["network"].get(m, []):
            device = (clean(n.get("network_device")) or "").lower()
            if device.startswith(VIRTUAL_NICS):
                continue
            ip = clean(n.get("network_ip"))
            if ip and _slash24(ip):
                owners[ip].add(m)
                nets_with[_slash24(ip)].add(m)
            gw = clean(n.get("network_gateway"))
            if gw:
                gw_candidates.add(gw)
    primary = {_slash24(m[1]) for m in machines if _slash24(m[1])}
    nets = sorted((n for n, ms in nets_with.items() if n in primary or len(ms) >= 2),
                  key=lambda n: ipaddress.ip_network(n))
    cols = {n: 2 + i for i, n in enumerate(nets)}
    gateways = {g for g in gw_candidates if _slash24(g) in cols}
    owners = {ip: ms for ip, ms in owners.items() if _slash24(ip) in cols}
    return nets, cols, owners, gateways


def write_ip_map(book, links, nets, cols, owners, gateways, rows, group_colors):
    s = SheetWriter(book, "IP Map", COLOR["ip"], links)
    s.header(1, ["Host"] + nets)
    for octet in range(1, 255):
        r = octet + 1
        s.put(r, 1, f".{octet}", bold=True, fg="57606A", align="center")
        for net, col in cols.items():
            ip = str(ipaddress.ip_network(net).network_address + octet)
            who = sorted(owners.get(ip, ()), key=machine_sort)
            if len(who) == 1:
                m = who[0]
                s.link(r, col, "Machines", rows["machines"][m], 1, m[0], bg=group_colors.get(m[2]), fg="24292F")
            elif len(who) > 1:
                s.put(r, col, "conflict: " + ", ".join(w[0] for w in who), bg=BAD[0], fg=BAD[1], bold=True)
            elif ip in gateways:
                s.put(r, col, "gateway", bg="24292F", fg="FFFFFF", bold=True, align="center")
            else:
                s.put(r, col, None)
    for col in cols.values():
        s.widths[col] = max(s.widths[col], 16)
    s.finish(freeze="B2", max_width=26)


def write_subnets(book, links, nets, cols, owners, gateways, rows):
    s = SheetWriter(book, "Subnets", COLOR["ip"], links)
    columns = ["Subnet", "Gateway", "Used", "Free", "Utilization", "Machines", "Groups"]
    s.header(1, columns)
    for i, net in enumerate(nets):
        r = i + 2
        base = ipaddress.ip_network(net)
        ips = [str(base.network_address + o) for o in range(1, 255)]
        used_ips = [ip for ip in ips if owners.get(ip) or ip in gateways]
        machines = {m for ip in ips for m in owners.get(ip, ())}
        groups = Counter(m[2] for m in machines)
        util = len(used_ips) / 254
        gws = [ip for ip in ips if ip in gateways]
        s.link(r, 1, "IP Map", 1, cols[net], net, bold=True)
        s.put(r, 2, ", ".join(gws) or None)
        s.put(r, 3, len(used_ips))
        s.put(r, 4, 254 - len(used_ips))
        s.put(r, 5, util, number_format="0%", bold=True,
              bg=HEAT[min(int(util * len(HEAT)), len(HEAT) - 1)])
        s.put(r, 6, len(machines))
        s.put(r, 7, ", ".join(f"{g} ×{n}" if n > 1 else g
                              for g, n in sorted(groups.items(), key=lambda x: (-x[1], natural(x[0])))) or None)
    s.finish(freeze="B2", filter_row=1, last_row=len(nets) + 1, last_col=len(columns), max_width=90)


# --------------------------------------------------------------------------- groups / overview

def write_groups(book, links, prepared, many, rows, preassign=False):
    by_group = defaultdict(list)
    for p in prepared:
        by_group[p["key"][2]].append(p)
    groups = sorted(by_group, key=natural)
    if preassign:  # first pass: only row numbers, so Machines can link to Groups
        for i, g in enumerate(groups):
            rows["groups"][g] = i + 2
        return

    s = SheetWriter(book, "Groups", COLOR["groups"], links)
    columns = ["Group", "Machines", "OS", "Platform", "Physical Cores", "Logical CPUs", "RAM (GiB)",
               "Disk (GiB)", "Subnets", "Top Services"]
    s.header(1, columns)

    def mix(values):
        c = Counter(v for v in values if v)
        return ", ".join(f"{k} ×{n}" for k, n in sorted(c.items(), key=lambda x: (-x[1], natural(x[0])))) or None

    totals = {k: sorted({sum(p[k] or 0 for p in by_group[g]) for g in groups})
              for k in ("phys", "logical", "ram", "disk_total")}
    for i, g in enumerate(groups):
        r = i + 2
        ps = by_group[g]
        first = min(rows["machines"][p["key"]] for p in ps)
        tools = Counter(clean(t.get("tool_name")) for p in ps for t in many["tools"].get(p["key"], []))
        s.link(r, 1, "Machines", first, 1, g, bold=True)
        s.put(r, 2, len(ps), bold=True)
        s.put(r, 3, mix(p["os_label"] for p in ps))
        s.put(r, 4, mix(p["platform"] for p in ps))
        for col, k, fmt in ((5, "phys", None), (6, "logical", None), (7, "ram", "#,##0.0"),
                            (8, "disk_total", "#,##0.0")):
            v = sum(p[k] or 0 for p in ps)
            s.put(r, col, round(v, 1) if isinstance(v, float) else v, number_format=fmt,
                  bg=bucket(v, totals[k], SEQUENTIAL))
        subnets = sorted({_slash24(p["key"][1]) for p in ps if _slash24(p["key"][1])}, key=natural)
        s.put(r, 9, ", ".join(subnets) or None)
        s.put(r, 10, ", ".join(f"{t} ×{n}" for t, n in tools.most_common(6) if t) or None)
    s.finish(freeze="B2", filter_row=1, last_row=len(groups) + 1, last_col=len(columns), max_width=70)


def write_overview(ws, links, stats, generated_at):
    s = SheetWriter.__new__(SheetWriter)
    s.ws, s.title, s.color, s.links, s.widths = ws, "Overview", COLOR["identity"], links, defaultdict(int)
    ws.title = "Overview"
    ws.sheet_properties.tabColor = COLOR["identity"]
    ws["A1"] = "Infrastructure documentation"
    ws["A1"].font = font(bold=True, size=18, color="24292F")
    ws["A2"] = f"Generated by Auto-Doc on {generated_at}. Every run overwrites this spreadsheet; do not edit by hand."
    ws["A2"].font = font(italic=True, color="57606A")
    ws.row_dimensions[1].height = 30

    kpis = [("Machines", stats["machines"]), ("Groups", stats["groups"]), ("Subnets", stats["subnets"]),
            ("Disks", stats["disks"]), ("NICs", stats["nics"]), ("Services", stats["services"]),
            ("Containers", stats["containers"])]
    for i, (label, value) in enumerate(kpis, start=1):
        top = ws.cell(row=4, column=i, value=value)
        top.font = font(bold=True, size=16, color="24292F")
        top.alignment = Alignment(horizontal="center")
        top.fill = fill("F6F8FA")
        bottom = ws.cell(row=5, column=i, value=label)
        bottom.font = font(color="57606A")
        bottom.alignment = Alignment(horizontal="center")
        bottom.fill = fill("F6F8FA")

    sheets = [
        ("Groups", "One row per group: size, OS mix, total capacity, subnets, top services.", COLOR["groups"]),
        ("Machines", "One row per machine: OS, CPU, memory, plus disk/NIC/service/container counts.",
         COLOR["identity"]),
        ("Storage", "Every mounted disk and volume, with size and type.", COLOR["storage"]),
        ("Network", "Every network interface: IP, subnet, gateway, MAC, state.", COLOR["network"]),
        ("IP Map", "Who uses which IP: one column per subnet, one row per last octet. Blank = free.",
         COLOR["ip"]),
        ("Subnets", "Utilization, gateways and groups per subnet.", COLOR["ip"]),
        ("Services", "What is installed where. Cell = version; green running, red stopped, amber not on boot.",
         COLOR["services"]),
        ("Service Details", "Every installed service with ports, install method and path.", COLOR["services"]),
        ("Containers", "Every Docker container: image, ports, networks, mounts.", COLOR["containers"]),
    ]
    for ci, h in enumerate(["Sheet", "What it answers"], start=1):
        c = ws.cell(row=7, column=ci, value=h)
        c.fill = fill("24292F")
        c.font = font(bold=True, color="FFFFFF")
    ws.merge_cells(start_row=7, start_column=2, end_row=7, end_column=7)
    for i, (name, desc, color) in enumerate(sheets):
        r = 8 + i
        s.link(r, 1, name, 1, 1, name, bold=True, fg=color, bg="F6F8FA")
        ws.cell(row=r, column=1).font = font(bold=True, color=color, underline="single")
        d = ws.cell(row=r, column=2, value=desc)
        d.font = font(color="24292F")
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=7)
    ws.column_dimensions["A"].width = 18
    for col in "BCDEFG":
        ws.column_dimensions[col].width = 14


# --------------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default="outputs")
    parser.add_argument("--output", default="outputs/auto-doc.xlsx")
    args = parser.parse_args()

    machines, one, many = build_model(args.input)
    if not machines:
        sys.exit(f"no machines found in {args.input}/*.json; run the collectors first")

    links = []
    rows = defaultdict(dict)
    rows["matrix_cells"] = []

    book = Workbook()
    overview = book.active

    # Row numbers are needed before the sheets that link to them exist, so lay
    # out the targets first (cheap passes), then write everything in tab order.
    tools, matrix_cols = services_layout(machines, many)
    nets, ip_cols, owners, gateways = ip_layout(machines, many)
    group_colors = categorical(m[2] for m in machines)

    # Pre-compute first-row positions of the one-to-many sheets.
    for key, stem in (("storage", "storage"), ("network", "network"), ("containers", "docker")):
        r = 3
        for m in machines:
            n = len(many[stem].get(m, []))
            if n:
                rows[key][m] = r
                r += n
    r = 3
    for m in machines:
        if many["tools"].get(m):
            rows["services"][m] = r
            r += 1

    prepared_stub = [{"key": m} for m in machines]
    write_groups(book, links, prepared_stub, many, rows, preassign=True)

    groups_ws = book.create_sheet("Groups")          # placeholder keeps tab order
    prepared = write_machines(book, links, machines, one, many, rows)
    write_storage(book, links, machines, many, rows)
    write_network(book, links, machines, many, rows, ip_cols)
    write_ip_map(book, links, nets, ip_cols, owners, gateways, rows, group_colors)
    write_subnets(book, links, nets, ip_cols, owners, gateways, rows)
    svc = write_services(book, links, machines, many, rows, tools, matrix_cols)
    write_service_details(book, links, machines, many, rows, matrix_cols)
    link_matrix(svc, rows)
    write_containers(book, links, machines, many, rows)

    book.remove(groups_ws)
    write_groups(book, links, prepared, many, rows)
    book.move_sheet("Groups", offset=-(len(book.sheetnames) - 2))

    stats = {
        "machines": len(machines), "groups": len({m[2] for m in machines}), "subnets": len(nets),
        "disks": sum(len(v) for v in many["storage"].values()),
        "nics": sum(len(v) for v in many["network"].values()),
        "services": sum(len(v) for v in many["tools"].values()),
        "containers": sum(len(v) for v in many["docker"].values()),
    }
    write_overview(overview, links, stats, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    book.save(out)
    links_path = out.with_suffix(".links.json")
    links_path.write_text(json.dumps(links, ensure_ascii=False))
    print(f"wrote {out} ({', '.join(book.sheetnames)}) and {len(links)} links to {links_path.name}; "
          + ", ".join(f"{k}={v}" for k, v in stats.items()))


if __name__ == "__main__":
    main()
