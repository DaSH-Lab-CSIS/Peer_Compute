#!/usr/bin/env python3
"""
Run this ONCE on your LOCAL machine (Mac/Linux with a browser) to obtain
a Google Drive OAuth token, then copy the token to utorda1.

Usage:
    pip install google-auth-oauthlib
    python gdrive_auth.py ~/.config/peercomp/credentials.json

It will open your browser, ask you to approve access, then save the token
to the same directory as credentials.json (as token.json).

After that, copy it to utorda1:
    scp ~/.config/peercomp/token.json peercompute@utorda1.dashlab.in:~/.config/peercomp/token.json
"""
import sys
import json
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("Missing dependency. Run:  pip install google-auth-oauthlib")
    sys.exit(1)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    creds_path = Path(sys.argv[1]).expanduser().resolve()
    if not creds_path.exists():
        print(f"credentials.json not found at: {creds_path}")
        sys.exit(1)

    token_path = creds_path.parent / "token.json"

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"\nToken saved to: {token_path}")
    print("\nNow copy it to utorda1:")
    print(f"  scp {token_path} peercompute@utorda1.dashlab.in:~/.config/peercomp/token.json")
    print("\nThen on utorda1 run the upload:")
    print("  cd ~/Serverless_Scheduler/testbed")
    print("  ../.venv/bin/python main.py --upload-only fairness_mix_20260527_195018")


if __name__ == "__main__":
    main()
