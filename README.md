# Auto-Doc: The Living CMDB & GitOps Documentation Engine

**Auto-Doc** is an agentless framework designed to automate the documentation of complex Linux ecosystems. By treating infrastructure and application metadata as version-controlled code, Auto-Doc transforms the nightmare of manual tracking into a dynamic, **GitOps-driven Source of Truth**.

## 💡 The Philosophy: "Infrastructure as Documentation"

In large-scale environments, static documentation (Wikis, Spreadsheets, or rigid DCIM tools like NetBox) is always out of date. Auto-Doc solves this by:

* **Universal Metadata Ingestor:** Document everything from physical hardware (`cpu_arch`) to dynamic application states (`backend_framework_version`) or storage topology (`storage_mountpoint`).

* **Zero-Footprint (Python-Less):** No prerequisites on target machines. If it has SSH and a shell or a CLI-command, it is documented.

* **GitOps Audit Trail:** Every change, from an IP swap to a container update, is captured as a Git commit, providing a perfect historical record of your entire fleet.

* **Visual Strategy:** Designed specifically for **Grafana** via the **Infinity Datasource**, allowing you to search, filter, and alert on documentation changes as easily as monitoring metrics.

## 🛠 Project Structure

```Plaintext
.
├── hosts.yaml          # Inventory of your entire fleet (VMs, Bare-metal)
├── main.yaml           # The Master Orchestrator
├── tasks/              # Logic units (The "Collectors")
│   ├── os.yaml         # OS-level metadata
│   ├── docker.yaml     # Container & Image states
│   ├── backend.yaml    # Application-specific versions/configs
│   └── ...
├── outputs/            # Flat JSON artifacts (The "Source of Truth")
│   ├── cpu.json
│   ├── storage.json
│   └── ...
└── README.md
```

## 📐 Rules of Development

To ensure the system remains scalable and the data remains clean for large number of machines, all contributions must follow these three mandates:

### 1. Zero-Footprint (Python-Less)

All data extraction must use the Ansible `raw` module.

* **Requirement:** Target machines must not require Python or any pre-installed agents. They just need to be able to handle SSH connections or receive GET requests.

* **Goal:** 100% compatibility across legacy, stripped-down, or hardened Linux distributions.

### 2. Non-Invasive (Read-Only)

**The "Look, Don't Touch" Rule:** Playbooks must never execute commands that modify the target system state.

* **Mandate:** Only use "Read" commands (e.g., `cat`, `grep`, `lsblk`, `df`, `curl GET`).

* **Restriction:** Strictly no `apt install`, `systemctl restart`, `rm`, or `POST/PUT` requests. Auto-Doc is a listener, not a configurator.

### 3. Component Isolation (Atomic POVs)

Each "Point of View" (POV) must be its own playbook in the `tasks/` directory.

* **Structure:** `tasks/network.yaml` produces `outputs/network.json`.

* **Reason:** This keeps logic maintainable and allows you to run specific documentation updates without taxing the entire network.

### 4. Unique Namespacing

Fields must be uniquely prefixed to prevent data collision when aggregating sources in Grafana.

* **Format:** `<component>_<field_name>`

* **Scalar vs. Multi-Value:**

    * *Single-Value:* `{"cpu_physical_cores": 8}`

    * *Multi-Value:* `{"storage_mountpoints": ""}` (Repeated entries times for a single `target_machine:target_ip` pair).

* **Rule:** Before adding a field, search the `outputs/` directory to ensure the name is unique.

## 🏃 Execution

To run the **Auto-Doc** engine, your control node requires SSH access to the target fleet via **root** with **Public Key Authentication**. Root access is necessary to read restricted system metadata (e.g., `/proc` or Docker sockets) without interactive password prompts.

### Run Command

```Bash
ansible-playbook -i hosts.yaml main.yaml -u root
```

### Prerequisites

* **SSH Key-Based Auth:** Your public key must be in the `/root/.ssh/authorized_keys` of all target machines.

* **Local Tools:** The control node requires `ansible` and `jq` installed to process and structure the metadata.

## 🔄 The GitOps Lifecycle

Auto-Doc is designed to run as a scheduled pipeline (e.g., a nightly GitLab CI job):

1. **Extract:** The pipeline runs `ansible-playbook` against the inventory.

2. **Commit:** New JSON snapshots are committed back to the Git repository.

3. **Diff:** Any change in the JSON files represents a physical or configuration change in the infrastructure.

4. **Expose:** The `outputs/` folder is served (via a simple json-exposer script) to a GET-able endpoint for any tool to consume.

5. **Visualize:** Use the **Infinity Datasource** to create unified tables, joining different JSON files on the `hostname` key.

## 📈 Why this over NetBox or Spreadsheets?

* **Ease of Maintenance:** No database migrations, no unwanted fields, and no complex UI configurations.

* **Total Flexibility:** Need to track a new field like `frontend_build_number`? Just add a 3-line shell command in a new task file.

* **Data Portability:** Flat JSON is the "universal language." It is trivial to transform these artifacts into CSV, SQL, or Markdown reports later if needed.

* **Unified Context:** See which machine has a specific IP or CPU count right next to your real-time performance graphs in Grafana.
