#!/usr/bin/env python3
"""
Lark User OAuth setup for Calendar access.
Run once to authorize - opens browser for user consent.
Saves user token to <MSGRELAY_HOME>/scripts/lark_user_token.json
"""
import os
import sys
import json
import time
import hashlib
import secrets as secrets_mod
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wacli_config import _load_secrets

LARK_BASE = "https://open.larksuite.com/open-apis"
LARK_AUTH_URL = f"{LARK_BASE}/authen/v1/authorize"
LARK_TOKEN_URL = "https://open.larksuite.com/open-apis/authen/v1/oidc/access_token"
REDIRECT_PORT = 5679
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"

# Required scopes for Calendar + Tasks + Bitable
# Using granular scopes to match app's configured permissions
SCOPES = [
    "calendar:calendar",
    "task:task:read",
    "task:task:write",
    "bitable:app",
]

TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lark_user_token.json")

auth_result = {"code": None, "error": None}


class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            auth_result["code"] = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body style='font-family:sans-serif;padding:40px;text-align:center'>"
                             b"<h2>&#x2705; Lark &#x6388;&#x6B0A;&#x6210;&#x529F;&#xFF01;</h2>"
                             b"<p>&#x53EF;&#x4EE5;&#x95DC;&#x9589;&#x9019;&#x500B;&#x8996;&#x7A97;&#x4E86;</p>"
                             b"</body></html>")
        elif "error" in params:
            auth_result["error"] = params.get("error_description", [params["error"][0]])[0]
            self.send_response(400)
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress logs


def main():
    secrets = _load_secrets()
    app_id = secrets.get("lark_app_id", "")
    app_secret = secrets.get("lark_app_secret", "")

    if not app_id:
        print("❌ Lark app_id not found in secrets")
        sys.exit(1)

    # Generate state for CSRF protection
    state = secrets_mod.token_hex(16)

    # Build auth URL
    scope_str = " ".join(SCOPES)
    params = urllib.parse.urlencode({
        "app_id": app_id,
        "redirect_uri": REDIRECT_URI,
        "scope": scope_str,
        "state": state,
    }, quote_via=urllib.parse.quote)
    auth_url = f"{LARK_AUTH_URL}?{params}"

    print("🔐 Opening browser for Lark authorization...")
    print(f"   Scopes: {scope_str}")
    print()
    webbrowser.open(auth_url)

    # Start local server to receive callback
    server = HTTPServer(("localhost", REDIRECT_PORT), OAuthHandler)
    server.timeout = 120  # 2 minute timeout

    print(f"⏳ Waiting for authorization (timeout: 2 min)...")
    server.handle_request()

    if auth_result["error"]:
        print(f"❌ Authorization failed: {auth_result['error']}")
        sys.exit(1)

    if not auth_result["code"]:
        print("❌ No authorization code received (timeout?)")
        sys.exit(1)

    code = auth_result["code"]
    print(f"✅ Got authorization code")

    # Exchange code for token - try different methods
    import requests
    
    app_resp = requests.post(
        f"{LARK_BASE}/auth/v3/app_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    app_data = app_resp.json()
    if app_data.get("code") != 0:
        print(f"❌ App auth failed: {app_data.get('msg')}")
        print(json.dumps(app_data, indent=2))
        sys.exit(1)
    app_token = app_data["app_access_token"]
    print(f"✅ App token obtained")

    # Try the user_access_token endpoint
    resp = requests.post(
        f"{LARK_BASE}/authen/v1/oidc/access_token",
        headers={"Authorization": f"Bearer {app_token}"},
        json={
            "grant_type": "authorization_code",
            "code": code,
        },
        timeout=10,
    )
    
    data = resp.json()
    print(f"Token response: code={data.get('code')} msg={data.get('msg','')}")
    print(f"Full response keys: {list(data.keys())}")
    if 'data' in data:
        print(f"data keys: {list(data['data'].keys()) if isinstance(data.get('data'), dict) else type(data['data'])}")
    print(f"Top-level access_token: {data.get('access_token', 'MISSING')[:20]}")
    
    if data.get("code") != 0:
        # Try alternative endpoint
        print("Trying alternative token endpoint...")
        resp2 = requests.post(
            f"{LARK_BASE}/auth/v3/user_access_token",
            headers={"Authorization": f"Bearer {app_token}"},
            json={
                "grant_type": "authorization_code",
                "code": code,
            },
            timeout=10,
        )
        data = resp2.json()
        print(f"Alt response: code={data.get('code')} msg={data.get('msg','')}")

    if resp.status_code != 200:
        print(f"❌ Token exchange failed: {resp.status_code}")
        print(resp.text[:300])
        sys.exit(1)

    data = resp.json()
    if data.get("code") != 0:
        print(f"❌ Token error: {data.get('msg', 'unknown')}")
        sys.exit(1)

    access_token = data.get("data", {}).get("access_token", data.get("access_token", ""))
    refresh_token = data.get("data", {}).get("refresh_token", data.get("refresh_token", ""))
    expires_in = data.get("data", {}).get("expires_in", data.get("expires_in", 7200))

    # Save tokens
    token_data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": time.time() + expires_in - 300,
        "created_at": time.time(),
    }

    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)
    os.chmod(TOKEN_FILE, 0o600)

    print(f"✅ User token saved to {TOKEN_FILE}")
    print(f"   Token: {access_token[:15]}...")
    print(f"   Expires in: {expires_in}s")
    print()
    print("✨ Lark Calendar authenticated!")


if __name__ == "__main__":
    main()
