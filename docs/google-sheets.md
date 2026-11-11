# Publishing Auto-Doc to Google Sheets

The last play in `main.yaml` builds `outputs/auto-doc.xlsx` from `outputs/*.json` and uploads it over one existing Google Sheet. The Sheet keeps the same URL, and every run replaces its contents.

Authentication uses a **Google service account**: a robot Google identity with a JSON key. Give it Editor access to one Sheet and it can update that Sheet without any browser login, so it works in nightly runs.

Everything secret lives in `secrets/`, which is gitignored (only `secrets/sheets.example.yaml` is tracked):

```
secrets/
├── sheets.example.yaml          # tracked template
├── sheets.yaml                  # your settings, gitignored
└── google-service-account.json  # your key, gitignored
```

## 1. Create the service account and key

You need the `gcloud` CLI and any Google account. Run these from the repo root. Pick your own project ID: it must be globally unique, 6–30 characters, lowercase letters, digits and dashes.

```bash
export PROJECT_ID=autodoc-sheets-<your-org>
gcloud auth login
gcloud projects create "$PROJECT_ID" --name="Auto-Doc Sheets"
gcloud config set project "$PROJECT_ID"
```

Two APIs are needed: Drive uploads the xlsx and converts it into the Sheet, and Sheets re-creates the links between tabs afterwards.

```bash
gcloud services enable drive.googleapis.com sheets.googleapis.com
```

Create the service account and download its key straight into `secrets/`:

```bash
gcloud iam service-accounts create autodoc-sheets --display-name="Auto-Doc Sheets"
mkdir -p secrets
gcloud iam service-accounts keys create secrets/google-service-account.json \
  --iam-account="autodoc-sheets@${PROJECT_ID}.iam.gserviceaccount.com"
chmod 600 secrets/google-service-account.json
```

Print the service account's email. You need it in step 2.

```bash
jq -r .client_email secrets/google-service-account.json
```

> Prefer the web console? In console.cloud.google.com: create a project, then enable https://console.cloud.google.com/apis/library/drive.googleapis.com and https://console.cloud.google.com/apis/library/sheets.googleapis.com, then **IAM & Admin → Service Accounts → Create service account** (no roles needed), then open it and go to **Keys → Add key → JSON**. Save the downloaded file as `secrets/google-service-account.json`.

## 2. Create the Sheet and share it

1. Open https://sheets.new and name the Sheet, e.g. `Auto-Doc Fleet`.
2. Click **Share**, paste the service account email from step 1, set it to **Editor**, untick "Notify people", then click **Share**.
3. Copy the Sheet ID from the URL: `https://docs.google.com/spreadsheets/d/`**`<SHEET_ID>`**`/edit`

The service account doesn't own the Sheet; you do. That way it needs no Drive storage of its own, and you can share the Sheet with the team as Viewer as usual.

## 3. Fill in the settings

```bash
cp secrets/sheets.example.yaml secrets/sheets.yaml
sed -i 's/^autodoc_sheet_id: .*/autodoc_sheet_id: "<SHEET_ID>"/' secrets/sheets.yaml
cat secrets/sheets.yaml
```

`autodoc_google_credentials` already points to `secrets/google-service-account.json`. Relative paths are resolved from the repo root; absolute paths work too.

## 4. Install the Python deps and run

The deps go into the Python that runs Ansible. If you installed Ansible with pipx, use `pipx inject ansible openpyxl google-api-python-client google-auth` instead.

```bash
pip install -r scripts/requirements.txt
ansible-playbook main.yaml --tags sheets
```

`--tags sheets` publishes the `outputs/` you already have. A plain `ansible-playbook main.yaml` collects everything and then publishes.

## CI / Kubernetes alternative

If no `secrets/sheets.yaml` exists, the play falls back to environment variables:

```bash
export AUTODOC_SHEET_ID=<SHEET_ID>
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/google-service-account.json
ansible-playbook main.yaml --tags sheets
```

In GitLab CI, store the key as a **File** variable named `GOOGLE_APPLICATION_CREDENTIALS`, and the ID as a normal variable named `AUTODOC_SHEET_ID`.

## Troubleshooting

| Message | Fix |
|---|---|
| `Google Sheets upload skipped` | `secrets/sheets.yaml` is missing or `autodoc_sheet_id` is empty. |
| `sheet ... not found — is it shared with ...?` | The Sheet isn't shared with the service account email, or the ID is wrong. |
| `no write access` | The service account is shared as Viewer/Commenter; change it to **Editor**. |
| `... is not a Google Sheet — refusing to overwrite` | The ID points at an uploaded .xlsx or another file type. Use a native Google Sheet (https://sheets.new). |
| `the drive.googleapis.com / sheets.googleapis.com API is disabled` | Open the link in the message, click **Enable**, wait a minute, run again. |
| Key creation blocked by `iam.disableServiceAccountKeyCreation` | Your Google Workspace org forbids keys. Ask the org admin for an exception, or create the project under a personal Google account. |
| `Unable to find the server at oauth2.googleapis.com` / timeouts | The control node has no direct route to Google. Set `autodoc_https_proxy: "http://<host>:<port>"` in `secrets/sheets.yaml` (or export `HTTPS_PROXY`). |

## Rotating or revoking the key

```bash
gcloud iam service-accounts keys list --iam-account="autodoc-sheets@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud iam service-accounts keys delete <KEY_ID> --iam-account="autodoc-sheets@${PROJECT_ID}.iam.gserviceaccount.com"
```

Then create a new key with the `keys create` command from step 1. Removing the service account from the Sheet's Share list also cuts its access immediately.
