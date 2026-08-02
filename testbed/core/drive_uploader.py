"""
Google Drive uploader for enriched run artefacts.

Auth model
----------
First run  : opens browser for OAuth consent -> caches token at ~/.config/peercomp/token.json
Subsequent : silently refreshes token from cache; no browser needed

Folder layout on Drive
----------------------
peercomp_runs/
    <run_id>/
        <run_id>_jobs_enriched.csv
        <run_id>_jobs_enriched.json
        <run_id>_metrics.json          (if present)

Usage (standalone)
------------------
    from core.drive_uploader import upload_run_artefacts
    upload_run_artefacts(run_id, results_dir, credentials_file)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Google API imports (optional dependency: google-api-python-client et al.)
# ---------------------------------------------------------------------------
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    _GDRIVE_AVAILABLE = True
except ImportError:
    _GDRIVE_AVAILABLE = False

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

_DEFAULT_TOKEN_PATH = Path.home() / ".config" / "peercomp" / "token.json"
_DEFAULT_CREDENTIALS_PATH = Path.home() / ".config" / "peercomp" / "credentials.json"

_TOP_LEVEL_FOLDER = "peercomp_runs"


def _ensure_gdrive():
    if not _GDRIVE_AVAILABLE:
        raise ImportError(
            "Google Drive libraries are missing. "
            "Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        )


def _get_credentials(credentials_file: Optional[str] = None, token_file: Optional[str] = None) -> "Credentials":
    """Load or refresh OAuth2 credentials, running the browser flow if needed."""
    creds_path = Path(credentials_file) if credentials_file else _DEFAULT_CREDENTIALS_PATH
    token_path = Path(token_file) if token_file else _DEFAULT_TOKEN_PATH

    if not creds_path.exists():
        raise FileNotFoundError(
            f"Google OAuth credentials not found at {creds_path}.\n"
            "Download them from Google Cloud Console -> APIs & Services -> Credentials "
            "-> OAuth 2.0 Client IDs -> Download JSON, then place the file at:\n"
            f"  {creds_path}"
        )

    token_path.parent.mkdir(parents=True, exist_ok=True)
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            # Loopback redirect: works for Desktop app OAuth clients, no port-forwarding needed.
            # Google redirects to http://localhost/?code=... which fails to load (expected)
            # and the user copies the code= value from the browser address bar.
            flow.redirect_uri = "http://localhost"
            auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
            print("\n" + "=" * 70)
            print("Google Drive OAuth required (one-time setup)")
            print("=" * 70)
            print("1. Open this URL in your browser (on your local machine):")
            print(f"\n   {auth_url}\n")
            print("2. Sign in as malhotra.arnav.201@gmail.com and approve access.")
            print("3. Your browser will redirect to http://localhost and show")
            print("   'This site can't be reached' - that is expected.")
            print("   Look at the browser address bar. It will look like:")
            print("   http://localhost/?code=4/0AX4XfWi...&scope=...")
            print("   Copy everything between 'code=' and '&scope' (or end of URL).")
            print("4. Paste that code below and press Enter.")
            print("=" * 70)
            code = input("\nAuthorization code: ").strip()
            flow.fetch_token(code=code)
            creds = flow.credentials
        with open(token_path, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())

    return creds


def _get_or_create_folder(service, name: str, parent_id: Optional[str] = None) -> str:
    """Return Drive folder ID, creating the folder if it doesn't exist."""
    query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    result = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def _upload_file(service, local_path: Path, parent_id: str) -> dict:
    """Upload a single file to Drive folder, overwriting if same name exists."""
    name = local_path.name

    # Remove existing file with the same name in that folder to avoid duplicates
    query = f"name='{name}' and '{parent_id}' in parents and trashed=false"
    existing = service.files().list(q=query, spaces="drive", fields="files(id)").execute()
    for f in existing.get("files", []):
        service.files().delete(fileId=f["id"]).execute()

    mime = "application/json" if local_path.suffix == ".json" else "text/csv"
    media = MediaFileUpload(str(local_path), mimetype=mime, resumable=True)
    file_meta = {"name": name, "parents": [parent_id]}
    uploaded = service.files().create(body=file_meta, media_body=media, fields="id, webViewLink").execute()
    return uploaded


def upload_run_artefacts(
    run_id: str,
    results_dir: str,
    credentials_file: Optional[str] = None,
    token_file: Optional[str] = None,
) -> dict:
    """
    Upload enriched artefacts for *run_id* into Drive under:
        peercomp_runs/<run_id>/

    Returns a dict with keys:
        folder_link  : web link to the run subfolder
        uploaded     : list of {name, link} for each uploaded file
    """
    _ensure_gdrive()

    results = Path(results_dir)
    csv_dir = results / "csv"
    json_dir = results / "json"

    candidates = [
        csv_dir / f"{run_id}_jobs_enriched.csv",
        json_dir / f"{run_id}_jobs_enriched.json",
        json_dir / f"{run_id}_metrics.json",
    ]
    artefacts = [p for p in candidates if p.exists()]

    if not artefacts:
        raise FileNotFoundError(
            f"No enriched artefacts found for run '{run_id}' under {results_dir}. "
            "Run enrichment first with --enrich or --enrich-after-run."
        )

    creds = _get_credentials(credentials_file, token_file)
    service = build("drive", "v3", credentials=creds)

    top_folder_id = _get_or_create_folder(service, _TOP_LEVEL_FOLDER)
    run_folder_id = _get_or_create_folder(service, run_id, parent_id=top_folder_id)

    run_folder_link = f"https://drive.google.com/drive/folders/{run_folder_id}"

    uploaded_files = []
    for path in artefacts:
        info = _upload_file(service, path, run_folder_id)
        uploaded_files.append({"name": path.name, "link": info.get("webViewLink", "")})

    return {
        "folder_link": run_folder_link,
        "uploaded": uploaded_files,
    }
