#!/usr/bin/env python3
"""
Antigravity History Sync - Google Drive Client
Handles:
- OAuth 2.0 authorization code flow with PKCE via local loopback web server.
- Secure storage of tokens in ~/.gemini/config/gdrive_auth.json.
- Automatic token refresh.
- Finding/creating the remote "AntigravitySync" folder on Google Drive.
- Reading and updating the remote registry.json.
- Uploading and downloading conversation archive blobs (.agyzip).
Uses standard Python library (urllib.request, json, http.server, hashlib, secrets) with zero pip dependencies!
"""

import os
import sys
import re
import json
import time
import base64
import hashlib
import secrets
import webbrowser
import urllib.request
import urllib.parse
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple


# Default community Google OAuth client credentials for Desktop Applications
DEFAULT_CLIENT_ID = os.environ.get("AGY_GDRIVE_CLIENT_ID", "789645123987-example.apps.googleusercontent.com")
DEFAULT_CLIENT_SECRET = os.environ.get("AGY_GDRIVE_CLIENT_SECRET", "GOCSPX-example_client_secret")

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"
SCOPE = "https://www.googleapis.com/auth/drive.file"


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handles OAuth 2.0 loopback redirect."""
    server: Any

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            self.server.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"""
            <html>
            <head><title>Antigravity Sync - Authenticated</title></head>
            <body style="font-family: system-ui, sans-serif; text-align: center; padding-top: 50px; background: #0f172a; color: #f8fafc;">
                <h1 style="color: #38bdf8;">&#10004; Google Drive Connected!</h1>
                <p>Authentication successful. You can close this browser tab and return to Antigravity.</p>
            </body>
            </html>
            """)
        else:
            error = params.get("error", ["Unknown error"])[0]
            self.server.auth_error = error
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<html><body><h1>Authentication Failed</h1><p>{error}</p></body></html>".encode("utf-8"))

    def log_message(self, format, *args):
        # Suppress server logging to terminal
        pass


class GDriveSyncClient:
    """Manages Google Drive authentication, registry sync, and file transfers."""

    def __init__(self, config_dir: Optional[Path] = None, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.config_dir = config_dir or (Path.home() / ".gemini" / "config")
        self.auth_file = self.config_dir / "gdrive_auth.json"
        self.credentials_file = self.config_dir / "gdrive_credentials.json"
        self._tokens: Optional[Dict[str, Any]] = None
        
        # Load credentials from config file, parameters, or env vars
        self.client_id, self.client_secret = self._resolve_credentials(client_id, client_secret)

    @staticmethod
    def _sanitize_secret(val: str) -> str:
        """Strips accidental JSON syntax, quotes, and whitespace from secret."""
        if not val:
            return ""
        val = val.strip().strip('"').strip("'")
        match = re.search(r'(GOCSPX-[a-zA-Z0-9_\-]+)', val)
        if match:
            return match.group(1)
        return val.split('"')[0].split(',')[0].strip()

    @staticmethod
    def _sanitize_id(val: str) -> str:
        """Strips accidental JSON syntax, quotes, and whitespace from client id."""
        if not val:
            return ""
        val = val.strip().strip('"').strip("'")
        match = re.search(r'([0-9]+-[a-zA-Z0-9_\-]+\.apps\.googleusercontent\.com)', val)
        if match:
            return match.group(1)
        return val.split('"')[0].split(',')[0].strip()

    def _resolve_credentials(self, client_id: Optional[str], client_secret: Optional[str]) -> Tuple[str, str]:
        """Resolves credentials from parameters, credentials file, local credentials.json, or env."""
        if client_id and client_secret:
            return self._sanitize_id(client_id), self._sanitize_secret(client_secret)

        # 1. Check ~/.gemini/config/gdrive_credentials.json
        if self.credentials_file.exists():
            try:
                with open(self.credentials_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    c_id = data.get("client_id") or data.get("installed", {}).get("client_id")
                    c_sec = data.get("client_secret") or data.get("installed", {}).get("client_secret")
                    if c_id and c_sec:
                        return self._sanitize_id(c_id), self._sanitize_secret(c_sec)
            except Exception:
                pass

        # 2. Check local credentials.json in current directory or workspace
        local_creds = Path.cwd() / "credentials.json"
        if local_creds.exists():
            try:
                with open(local_creds, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    inst = data.get("installed") or data.get("web") or data
                    c_id = inst.get("client_id")
                    c_sec = inst.get("client_secret")
                    if c_id and c_sec:
                        return self._sanitize_id(c_id), self._sanitize_secret(c_sec)
            except Exception:
                pass

        # 3. Check environment variables
        env_id = os.environ.get("AGY_GDRIVE_CLIENT_ID")
        env_sec = os.environ.get("AGY_GDRIVE_CLIENT_SECRET")
        if env_id and env_sec:
            return self._sanitize_id(env_id), self._sanitize_secret(env_sec)

        return DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET

    def has_valid_client_credentials(self) -> bool:
        """Returns True if client credentials are set and not an example placeholder."""
        if not self.client_id or not self.client_secret:
            return False
        if "example" in self.client_id.lower() or "example" in self.client_secret.lower():
            return False
        return True

    def save_client_credentials(self, client_id: str, client_secret: str) -> None:
        """Saves Google OAuth client ID and Secret to ~/.gemini/config/gdrive_credentials.json."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.client_id = self._sanitize_id(client_id)
        self.client_secret = self._sanitize_secret(client_secret)
        with open(self.credentials_file, "w", encoding="utf-8") as f:
            json.dump({"client_id": self.client_id, "client_secret": self.client_secret}, f, indent=2)

    def import_credentials_from_json(self, json_path: Path) -> bool:
        """Imports Google Cloud credentials from a downloaded client_secret_*.json file."""
        json_path = Path(json_path).expanduser()
        if not json_path.exists():
            return False
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            inst = data.get("installed") or data.get("web") or data
            c_id = inst.get("client_id")
            c_sec = inst.get("client_secret")
            if c_id and c_sec:
                self.save_client_credentials(c_id, c_sec)
                return True
        except Exception:
            return False
        return False

    def is_authenticated(self) -> bool:
        """Returns True if valid or refreshable tokens are saved."""
        tokens = self.load_tokens()
        return bool(tokens and ("refresh_token" in tokens or "access_token" in tokens))

    def load_tokens(self) -> Optional[Dict[str, Any]]:
        """Loads tokens from disk."""
        if self._tokens:
            return self._tokens
        if self.auth_file.exists():
            try:
                with open(self.auth_file, "r", encoding="utf-8") as f:
                    self._tokens = json.load(f)
                    return self._tokens
            except Exception:
                return None
        return None

    def save_tokens(self, tokens: Dict[str, Any]) -> None:
        """Saves tokens to disk."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._tokens = tokens
        with open(self.auth_file, "w", encoding="utf-8") as f:
            json.dump(tokens, f, indent=2)

    def logout(self) -> None:
        """Removes local authentication tokens."""
        self._tokens = None
        if self.auth_file.exists():
            self.auth_file.unlink()

    def start_oauth_flow(self, port: int = 49281) -> bool:
        """
        Runs the PKCE OAuth 2.0 loopback flow in the browser.
        Returns True on success.
        """
        # Generate PKCE verifier and challenge
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

        redirect_uri = f"http://127.0.0.1:{port}/callback"

        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }

        auth_url = f"{AUTH_URI}?{urllib.parse.urlencode(params)}"

        # Start local callback server
        server = HTTPServer(("127.0.0.1", port), OAuthCallbackHandler)
        server.auth_code = None
        server.auth_error = None

        print(f"[*] Opening browser for Google Drive authentication...\n{auth_url}")
        webbrowser.open(auth_url)

        # Wait for redirect
        while server.auth_code is None and server.auth_error is None:
            server.handle_request()

        if server.auth_error:
            print(f"[!] Authentication failed: {server.auth_error}", file=sys.stderr)
            return False

        # Exchange code for tokens
        token_payload = urllib.parse.urlencode({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": server.auth_code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }).encode("utf-8")

        req = urllib.request.Request(TOKEN_URI, data=token_payload, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                token_data = json.loads(resp.read().decode("utf-8"))
                token_data["expires_at"] = time.time() + token_data.get("expires_in", 3600)
                self.save_tokens(token_data)
                return True
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8")
                print(f"[!] Token exchange failed ({e.code}): {err_body}", file=sys.stderr)
            except Exception:
                print(f"[!] Token exchange failed: {e}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"[!] Token exchange failed: {e}", file=sys.stderr)
            return False

    def get_access_token(self) -> Optional[str]:
        """Returns a valid access token, automatically refreshing if expired."""
        tokens = self.load_tokens()
        if not tokens:
            return None

        # Check if expired
        expires_at = tokens.get("expires_at", 0)
        if time.time() >= expires_at - 60 and "refresh_token" in tokens:
            # Refresh token
            refresh_payload = urllib.parse.urlencode({
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": tokens["refresh_token"],
                "grant_type": "refresh_token",
            }).encode("utf-8")

            req = urllib.request.Request(TOKEN_URI, data=refresh_payload, method="POST")
            try:
                with urllib.request.urlopen(req) as resp:
                    new_tokens = json.loads(resp.read().decode("utf-8"))
                    tokens["access_token"] = new_tokens["access_token"]
                    tokens["expires_at"] = time.time() + new_tokens.get("expires_in", 3600)
                    self.save_tokens(tokens)
            except Exception as e:
                print(f"[!] Warning: Token refresh failed: {e}", file=sys.stderr)
                return tokens.get("access_token")

        return tokens.get("access_token")

    def _request(self, endpoint: str, method: str = "GET", data: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None) -> Any:
        """Executes an authenticated Google Drive API request."""
        token = self.get_access_token()
        if not token:
            raise RuntimeError("Not authenticated with Google Drive. Please run 'agy-sync login'.")

        url = endpoint if endpoint.startswith("http") else f"{DRIVE_API_BASE}/{endpoint}"
        req_headers = {"Authorization": f"Bearer {token}"}
        if headers:
            req_headers.update(headers)

        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    return json.loads(resp.read().decode("utf-8"))
                return resp.read()
        except urllib.error.HTTPError as e:
            raw_body = ""
            err_msg = ""
            reasons = []
            try:
                raw_body = e.read().decode("utf-8")
                err_data = json.loads(raw_body)
                err_obj = err_data.get("error", {})
                err_msg = err_obj.get("message", raw_body)
                errors_list = err_obj.get("errors", [])
                reasons = [item.get("reason", "") for item in errors_list if isinstance(item, dict)]
            except Exception:
                err_msg = raw_body or str(e)

            # Determine project ID for console link
            proj_id = self.client_id.split("-")[0] if self.client_id and "-" in self.client_id else ""
            proj_param = f"?project={proj_id}" if proj_id else ""

            if e.code == 403:
                if (
                    "has not been used in project" in err_msg
                    or "disabled" in err_msg
                    or "accessNotConfigured" in reasons
                    or "SERVICE_DISABLED" in raw_body
                ):
                    raise RuntimeError(
                        f"Google Drive API is NOT enabled in your Google Cloud Project ({proj_id}).\n\n"
                        f"👉 To enable it with 1 click, open this link in your browser:\n"
                        f"   https://console.cloud.google.com/apis/library/drive.googleapis.com{proj_param}\n\n"
                        f"Click the blue 'ENABLE' button, wait ~30-60 seconds, and retry."
                    ) from e
                elif "insufficientPermissions" in reasons or "The caller does not have permission" in err_msg:
                    raise RuntimeError(
                        f"Google Drive permission error (403): {err_msg}\n"
                        f"Please verify your OAuth credentials and ensure your Google account is added as a Test User."
                    ) from e
                else:
                    raise RuntimeError(f"Google Drive API 403 Forbidden: {err_msg}") from e
            elif e.code == 401:
                raise RuntimeError(
                    f"Google Drive session unauthorized or expired (401): {err_msg}\n"
                    f"Run 'agy-sync login' to reconnect."
                ) from e
            else:
                raise RuntimeError(f"Google Drive API Error {e.code}: {err_msg}") from e

    def get_or_create_sync_folder(self) -> str:
        """Locates or creates the 'AntigravitySync' folder in Google Drive."""
        query = urllib.parse.quote("name = 'AntigravitySync' and mimeType = 'application/vnd.google-apps.folder' and trashed = false")
        res = self._request(f"files?q={query}&spaces=drive&fields=files(id,name)")
        files = res.get("files", [])
        if files:
            return files[0]["id"]

        # Create folder
        meta = json.dumps({
            "name": "AntigravitySync",
            "mimeType": "application/vnd.google-apps.folder"
        }).encode("utf-8")

        res = self._request("files", method="POST", data=meta, headers={"Content-Type": "application/json; charset=UTF-8"})
        return res["id"]

    def get_or_create_subfolder(self, parent_id: str, folder_name: str) -> str:
        """Locates or creates a subfolder inside AntigravitySync."""
        query = urllib.parse.quote(f"name = '{folder_name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false")
        res = self._request(f"files?q={query}&spaces=drive&fields=files(id,name)")
        files = res.get("files", [])
        if files:
            return files[0]["id"]

        meta = json.dumps({
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id]
        }).encode("utf-8")

        res = self._request("files", method="POST", data=meta, headers={"Content-Type": "application/json; charset=UTF-8"})
        return res["id"]

    def get_remote_registry(self, sync_folder_id: Optional[str] = None) -> Dict[str, Any]:
        """Fetches registry.json from Google Drive."""
        folder_id = sync_folder_id or self.get_or_create_sync_folder()
        query = urllib.parse.quote(f"name = 'registry.json' and '{folder_id}' in parents and trashed = false")
        res = self._request(f"files?q={query}&spaces=drive&fields=files(id,name)")
        files = res.get("files", [])
        if not files:
            return {"version": 1, "updatedAt": "", "conversations": {}}

        file_id = files[0]["id"]
        content = self._request(f"files/{file_id}?alt=media")
        try:
            return json.loads(content.decode("utf-8"))
        except Exception:
            return {"version": 1, "updatedAt": "", "conversations": {}}

    def upload_file(self, parent_folder_id: str, file_name: str, file_path: Path, mime_type: str = "application/octet-stream") -> str:
        """Uploads or updates a file inside a Google Drive folder using multipart upload."""
        # Check if file already exists
        query = urllib.parse.quote(f"name = '{file_name}' and '{parent_folder_id}' in parents and trashed = false")
        res = self._request(f"files?q={query}&spaces=drive&fields=files(id,name)")
        existing_files = res.get("files", [])

        file_size = file_path.stat().st_size
        with open(file_path, "rb") as f:
            file_data = f.read()

        boundary = "===============AGYSYNCBOUNDARY=="

        if existing_files:
            file_id = existing_files[0]["id"]
            # In Google Drive v3, PATCH /files/{id} cannot include 'parents' in metadata
            meta = json.dumps({"name": file_name})
            body = (
                f"--{boundary}\r\n"
                f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{meta}\r\n"
                f"--{boundary}\r\n"
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8") + file_data + f"\r\n--{boundary}--\r\n".encode("utf-8")

            headers = {"Content-Type": f"multipart/related; boundary={boundary}"}
            upload_url = f"{DRIVE_UPLOAD_BASE}/files/{file_id}?uploadType=multipart"
            res = self._request(upload_url, method="PATCH", data=body, headers=headers)
            return file_id
        else:
            meta = json.dumps({"name": file_name, "parents": [parent_folder_id]})
            body = (
                f"--{boundary}\r\n"
                f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{meta}\r\n"
                f"--{boundary}\r\n"
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8") + file_data + f"\r\n--{boundary}--\r\n".encode("utf-8")

            headers = {"Content-Type": f"multipart/related; boundary={boundary}"}
            upload_url = f"{DRIVE_UPLOAD_BASE}/files?uploadType=multipart"
            res = self._request(upload_url, method="POST", data=body, headers=headers)
            return res["id"]

    def download_file(self, file_id: str, dest_path: Path) -> None:
        """Downloads a file from Google Drive to dest_path."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        content = self._request(f"files/{file_id}?alt=media")
        with open(dest_path, "wb") as f:
            f.write(content)
