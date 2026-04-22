"""`memstack login` / `logout` — device-code authentication."""

from __future__ import annotations

import sys
import time
from typing import Any

import click
import httpx

from ..auth import CREDENTIALS_FILE, clear_credentials, save_api_key
from ..client import ApiError, base_url, die, emit, request


def _frontend_url_for(verification_uri: str) -> str:
    """Guess the browser-facing URL from the API URL.

    Keep this simple: use the same host as the API, and strip a trailing
    ':8000' (default API port) so users land on the Vite dev server at
    :3000 when running locally. In production, API and frontend share the
    same host, so we leave the URL as-is.
    """
    api_root = base_url()
    if api_root.endswith(":8000"):
        api_root = api_root[: -len(":8000")] + ":3000"
    if verification_uri.startswith("http"):
        return verification_uri
    return api_root.rstrip("/") + verification_uri


@click.command("login", help="Authenticate via device-code and store the token.")
@click.option("--no-browser", is_flag=True, help="Do not open the browser automatically.")
@click.pass_context
def login(ctx: click.Context, no_browser: bool) -> None:
    as_json = bool(ctx.obj.get("json"))

    try:
        resp: dict[str, Any] = request("POST", "/auth/device/code", json={})
    except ApiError as e:
        die(f"failed to start device flow: {e}")

    device_code = resp["device_code"]
    user_code = resp["user_code"]
    interval = int(resp.get("interval", 5))
    expires_in = int(resp.get("expires_in", 600))
    verify_uri = _frontend_url_for(resp.get("verification_uri_complete") or resp.get("verification_uri", "/device"))

    if as_json:
        emit(
            {"stage": "pending", "verification_uri": verify_uri, "user_code": user_code},
            as_json=True,
        )
    else:
        print(f"Open:  {verify_uri}")
        print(f"Code:  {user_code}")
        print(f"(expires in {expires_in}s, polling every {interval}s)")
        if not no_browser:
            try:
                import webbrowser

                webbrowser.open(verify_uri)
            except Exception:  # pragma: no cover
                pass

    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)
        try:
            token_resp = request(
                "POST", "/auth/device/token", json={"device_code": device_code}
            )
        except ApiError as e:
            if e.status_code == 428:
                continue
            if e.status_code == 410:
                die("login expired before approval. Run `memstack login` again.")
            die(f"polling failed: {e}")
        access_token = token_resp.get("access_token")
        if not access_token:
            die("server returned no access_token")
        path = save_api_key(access_token)
        if as_json:
            emit({"stage": "approved", "credentials_file": str(path)}, as_json=True)
        else:
            print(f"Logged in. Credentials saved to {path}")
        return
    die("login timed out before approval.")


@click.command("logout", help="Remove the stored API key.")
@click.pass_context
def logout(ctx: click.Context) -> None:
    removed = clear_credentials()
    if ctx.obj.get("json"):
        emit({"removed": removed, "path": str(CREDENTIALS_FILE)}, as_json=True)
    else:
        if removed:
            print(f"Removed {CREDENTIALS_FILE}")
        else:
            print("No credentials file to remove.", file=sys.stderr)


__all__ = ["login", "logout", "httpx"]  # keep httpx re-export defensive (unused but imported for typing).
