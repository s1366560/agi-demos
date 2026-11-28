"""Publish a packaged release to an OCI Distribution registry by immutable digest."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
import rfc8785

_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
_ARTIFACT = "application/vnd.memstack.plugin.v2"
_LAYER = "application/vnd.memstack.plugin.bundle.v2+zip"


def _location(registry: str, repository: str) -> str:
    url = urlsplit(registry)
    if (
        not url.hostname
        or url.username is not None
        or url.password is not None
        or url.path not in ("", "/")
        or url.query
        or url.fragment
        or url.scheme not in ("https", "http")
        or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"})
    ):
        raise ValueError("expected an HTTPS registry origin or a loopback test registry")
    if (
        not re.fullmatch(
            r"[a-z0-9]+(?:[._-]+[a-z0-9]+)*(?:/[a-z0-9]+(?:[._-]+[a-z0-9]+)*)*", repository
        )
        or len(repository) > 255
    ):
        raise ValueError("invalid OCI repository")
    return registry.rstrip("/") + "/v2/" + repository


def _require(response: httpx.Response, *codes: int) -> None:
    if response.status_code not in codes:
        raise ValueError(
            f"registry rejected {response.request.method} (HTTP {response.status_code})"
        )


def _descriptor(media: str, data: bytes) -> dict[str, str | int]:
    return {
        "mediaType": media,
        "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }


def _upload(client: httpx.Client, base: str, digest: str, data: bytes) -> None:
    existing = client.head(f"{base}/blobs/{digest}")
    _require(existing, 200, 404)
    if existing.status_code == 200:
        return
    start = client.post(base + "/blobs/uploads/")
    _require(start, 202)
    raw_location = start.headers.get("location")
    if not raw_location:
        raise ValueError("registry omitted the upload location")
    url = urlsplit(urljoin(str(start.request.url), raw_location))
    allowed = urlsplit(base)
    if (
        (url.scheme, url.netloc) != (allowed.scheme, allowed.netloc)
        or not url.path.startswith(allowed.path + "/blobs/uploads/")
        or url.fragment
    ):
        raise ValueError("registry returned an upload location outside the target repository")
    query = [(k, v) for k, v in parse_qsl(url.query, keep_blank_values=True) if k != "digest"]
    location = urlunsplit(url._replace(query=urlencode([*query, ("digest", digest)])))
    response = client.put(
        location, content=data, headers={"Content-Type": "application/octet-stream"}
    )
    _require(response, 201)


def publish(
    raw: bytes, registry: str, repository: str, *, token: str | None = None
) -> dict[str, object]:
    base = _location(registry, repository)
    if token is not None and not re.fullmatch(r"[a-zA-Z0-9._~+/-]+=*", token):
        raise ValueError("invalid registry token format")
    if not raw or len(raw) > 64 * 1024 * 1024:
        raise ValueError("expected a package of at most 64 MiB")
    with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
        descriptor = bundle.getinfo("bundle.json")
        if descriptor.file_size > 2 * 1024 * 1024:
            raise ValueError("oversized bundle descriptor")
        info = json.loads(bundle.read(descriptor))
    if not isinstance(info, dict) or not all(
        isinstance(info.get(key), str) and info[key]
        for key in ("bundle_id", "version", "signature")
    ):
        raise ValueError("missing signed package identity")
    if (
        info.get("schema_version") != 2
        or len(base64.b64decode(info["signature"], validate=True)) != 64
    ):
        raise ValueError("expected a signed protocol-v2 package")
    config = b"{}"
    empty = _descriptor("application/vnd.oci.empty.v1+json", config)
    layer = _descriptor(_LAYER, raw)
    manifest = rfc8785.dumps(
        {
            "schemaVersion": 2,
            "mediaType": _MANIFEST,
            "artifactType": _ARTIFACT,
            "config": empty,
            "layers": [layer],
        }
    )
    revision = hashlib.sha256(manifest).hexdigest()
    headers = {"Authorization": "Bearer " + token} if token else {}
    with httpx.Client(timeout=30, headers=headers, follow_redirects=False) as client:
        _upload(client, base, str(empty["digest"]), config)
        _upload(client, base, str(layer["digest"]), raw)
        response = client.put(
            base + "/manifests/sha256:" + revision,
            content=manifest,
            headers={"Content-Type": _MANIFEST},
        )
        _require(response, 201)
        if response.headers.get("Docker-Content-Digest") != "sha256:" + revision:
            raise ValueError("registry did not acknowledge the published manifest digest")
    return {
        "plugin_id": info["bundle_id"],
        "version": info["version"],
        "artifact": {
            "registry": registry.rstrip("/"),
            "repository": repository,
            "manifest_sha256": revision,
        },
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--token-file", type=Path, help="Optional registry-scoped bearer token")
    args = parser.parse_args()
    try:
        token = args.token_file.read_text().strip() if args.token_file else None
        with args.package.open("rb") as stream:
            receipt = publish(
                stream.read(64 * 1024 * 1024 + 1), args.registry, args.repository, token=token
            )
    except httpx.HTTPError as error:
        parser.exit(1, f"Registry connection failed ({type(error).__name__})\n")
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Publish failed: {error}\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
