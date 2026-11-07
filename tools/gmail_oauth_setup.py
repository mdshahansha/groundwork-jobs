"""One-time Gmail sign-in for jw: get a long-lived refresh token and store it in .env.

Needs a Google Cloud OAuth client of type "Desktop app" (client ID and secret) whose consent screen
is published "In production" (in "Testing" Google expires refresh tokens after 7 days). The tool
opens Google's consent page, receives the answer on a 127.0.0.1 loopback port with PKCE and a state
check, exchanges the code, and writes JW_GMAIL_CLIENT_ID, JW_GMAIL_CLIENT_SECRET and
JW_GMAIL_REFRESH_TOKEN to the .env file (mode 600). Tokens are never printed. After this, jw renews
its 1-hour access tokens by itself (`jw.gmail.access_token`).

    python tools/gmail_oauth_setup.py --env /path/to/.env --client-id ... --client-secret ...
"""

import argparse
import base64
import hashlib
import http.server
import json
import os
from pathlib import Path
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]
KEYS = ("JW_GMAIL_CLIENT_ID", "JW_GMAIL_CLIENT_SECRET", "JW_GMAIL_REFRESH_TOKEN")


def write_env(path, values):
    """Replace or append `export KEY=value` lines; other lines are kept as they are."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    kept = [line for line in lines if not any(line.strip().removeprefix("export ").startswith(k + "=") for k in values)]
    kept += [f"export {k}={v}" for k, v in values.items()]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def authorize(client_id, client_secret, open_browser=webbrowser.open):
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(24)
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            if query.get("state") == state and "code" in query:
                result["code"] = query["code"]
                message = "jw: Gmail access granted. You can close this tab."
            else:
                result["error"] = query.get("error", "state_mismatch")
                message = "jw: sign-in failed (" + result["error"] + ")."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(message.encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": " ".join(SCOPES),
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    print("Opening Google sign-in. If no browser opens, visit:\n" + url, flush=True)
    open_browser(url)
    server.timeout = 300
    while not result:
        server.handle_request()
    server.server_close()
    if "code" not in result:
        sys.exit("Sign-in failed: " + result["error"])
    data = urllib.parse.urlencode({"code": result["code"], "client_id": client_id, "client_secret": client_secret,
                                   "redirect_uri": redirect, "grant_type": "authorization_code",
                                   "code_verifier": verifier}).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=data, method="POST"), timeout=30) as response:
        token = json.loads(response.read())
    if not token.get("refresh_token"):
        sys.exit("Google returned no refresh token; remove jw's access at myaccount.google.com/permissions and rerun.")
    granted = set(token.get("scope", "").split())
    missing = [s for s in SCOPES if s not in granted]
    if missing:
        sys.exit("Not all scopes were granted: " + ", ".join(missing))
    return token["refresh_token"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env", required=True, help="the .env file to update (outside the repository)")
    parser.add_argument("--client-id", default=os.environ.get("JW_GMAIL_CLIENT_ID"))
    parser.add_argument("--client-secret", default=os.environ.get("JW_GMAIL_CLIENT_SECRET"))
    args = parser.parse_args()
    if not (args.client_id and args.client_secret):
        parser.error("Pass --client-id and --client-secret (or set JW_GMAIL_CLIENT_ID / JW_GMAIL_CLIENT_SECRET).")
    refresh = authorize(args.client_id, args.client_secret)
    write_env(args.env, dict(zip(KEYS, (args.client_id, args.client_secret, refresh))))
    print(f"Saved {', '.join(KEYS)} to {args.env} (mode 600). Token not shown.")


if __name__ == "__main__":
    main()
