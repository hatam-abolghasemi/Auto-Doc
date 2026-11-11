#!/usr/bin/env python3
"""Overwrite an existing Google Sheet with a local .xlsx (same ID, same URL),
then re-create cross-sheet links.

1. Drive uploads the xlsx as new content of the Sheet and converts it in
   place: tabs, colors, widths, merged headers, frozen panes, filters carry over.
2. Internal xlsx links do not survive that conversion, so the links listed in
   <xlsx>.links.json (written by json-to-xlsx.py) are set again as cell links
   pointing at "#gid=<tab>&range=<cell>" through the Sheets API.

Auth is a Google service account shared on the Sheet as Editor. Needs the
Drive API and the Sheets API enabled in its Google Cloud project.

Usage:
    python3 scripts/xlsx-to-sheets.py \
        --file outputs/auto-doc.xlsx \
        --sheet-id 1AbC...xyz \
        --credentials /path/to/service-account.json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]  # covers the Sheets API too
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
LINKS_PER_BATCH = 1000


def a1_to_index(a1):
    """'C12' -> (row_index=11, col_index=2), zero-based."""
    letters, digits = re.fullmatch(r"([A-Z]+)(\d+)", a1).groups()
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - 64)
    return int(digits) - 1, col - 1


def api_error(exc, sa_email, what):
    text = str(exc)
    if "SERVICE_DISABLED" in text or "has not been used" in text:
        api = "sheets.googleapis.com" if "sheets" in text.lower() else "drive.googleapis.com"
        return (f"{what}: the {api} API is disabled in the service account's project. Enable it at "
                f"https://console.cloud.google.com/apis/library/{api} and run again")
    if exc.resp.status == 404:
        return f"{what}: sheet not found. Is it shared with {sa_email} as Editor?"
    if exc.resp.status == 403:
        return f"{what}: no write access. Share the Sheet with {sa_email} as Editor"
    return f"{what}: {exc}"


def upload(drive, sheet_id, path, sa_email):
    try:
        target = drive.files().get(fileId=sheet_id, fields="id,name,mimeType", supportsAllDrives=True).execute()
    except HttpError as exc:
        sys.exit(api_error(exc, sa_email, "checking the sheet"))
    if target["mimeType"] != SHEET_MIME:
        sys.exit(f"{target['name']} is {target['mimeType']}, not a Google Sheet; refusing to overwrite")
    try:
        return drive.files().update(
            fileId=sheet_id,
            media_body=MediaFileUpload(str(path), mimetype=XLSX_MIME, resumable=True),
            supportsAllDrives=True,
            fields="id,name,modifiedTime,webViewLink",
        ).execute()
    except HttpError as exc:
        sys.exit(api_error(exc, sa_email, "uploading the workbook"))


def relink(sheets, sheet_id, links, sa_email):
    try:
        meta = sheets.spreadsheets().get(spreadsheetId=sheet_id,
                                         fields="sheets.properties(sheetId,title)").execute()
    except HttpError as exc:
        sys.exit(api_error(exc, sa_email, "reading tab ids"))
    gid = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}

    requests, skipped = [], 0
    for link in links:
        if link["sheet"] not in gid or link["target_sheet"] not in gid:
            skipped += 1
            continue
        row, col = a1_to_index(link["cell"])
        uri = f"#gid={gid[link['target_sheet']]}&range={link['target_cell']}"
        requests.append({"updateCells": {
            "start": {"sheetId": gid[link["sheet"]], "rowIndex": row, "columnIndex": col},
            "rows": [{"values": [{
                "userEnteredFormat": {"textFormat": {"link": {"uri": uri}}},
                "textFormatRuns": [],   # drop any half-converted link left by the import
            }]}],
            "fields": "userEnteredFormat.textFormat.link,textFormatRuns",
        }})

    for i in range(0, len(requests), LINKS_PER_BATCH):
        try:
            sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id,
                                              body={"requests": requests[i:i + LINKS_PER_BATCH]}).execute()
        except HttpError as exc:
            sys.exit(api_error(exc, sa_email, f"setting links (batch {i // LINKS_PER_BATCH + 1})"))
    return len(requests), skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", required=True, help="xlsx to upload")
    parser.add_argument("--sheet-id", required=True, help="ID of the existing Google Sheet")
    parser.add_argument("--credentials", required=True, help="service account JSON key path")
    parser.add_argument("--links", help="links manifest (default: <file>.links.json next to the xlsx)")
    args = parser.parse_args()

    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if proxy and not httplib2.proxy_info_from_environment("https").isgood():
        sys.exit(f"HTTPS_PROXY={proxy} is set but httplib2 cannot use it: pip install pysocks")

    try:
        creds = service_account.Credentials.from_service_account_file(args.credentials, scopes=SCOPES)
    except (ValueError, OSError) as exc:  # google.auth MalformedError is a ValueError
        sys.exit(f"cannot load service account key {args.credentials}: {exc}")
    sa_email = creds.service_account_email

    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    updated = upload(drive, args.sheet_id, args.file, sa_email)
    print(f"updated '{updated['name']}' at {updated['modifiedTime']}")

    links_path = Path(args.links) if args.links else Path(args.file).with_suffix(".links.json")
    if links_path.exists():
        done, skipped = relink(sheets, args.sheet_id, json.loads(links_path.read_text()), sa_email)
        print(f"set {done} cross-sheet links" + (f" ({skipped} skipped: tab missing)" if skipped else ""))
    else:
        print(f"no {links_path.name}; skipped cross-sheet links")
    print(updated["webViewLink"])


if __name__ == "__main__":
    main()
