"""Serve content-addressed test releases over the OCI distribution read API."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from src.application.schemas.plugin_marketplace import MarketplaceArtifactSource
from src.infrastructure.plugins.package_registry import (
    MEMSTACK_ARTIFACT_TYPE,
    MEMSTACK_LAYER_MEDIA_TYPE,
    OCI_MANIFEST_MEDIA_TYPE,
)


@contextmanager
def serve_archive(raw: bytes, directory: Path) -> Iterator[MarketplaceArtifactSource]:
    layer = hashlib.sha256(raw).hexdigest()
    manifest = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": OCI_MANIFEST_MEDIA_TYPE,
            "artifactType": MEMSTACK_ARTIFACT_TYPE,
            "layers": [
                {
                    "digest": "sha256:" + layer,
                    "size": len(raw),
                    "mediaType": MEMSTACK_LAYER_MEDIA_TYPE,
                }
            ],
        }
    ).encode()
    digest = hashlib.sha256(manifest).hexdigest()
    repo = directory / "v2" / "fixtures" / "sample"
    for kind, name, content in (("manifests", digest, manifest), ("blobs", layer, raw)):
        (repo / kind).mkdir(parents=True)
        (repo / kind / ("sha256:" + name)).write_bytes(content)
    with ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(directory))
    ) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield MarketplaceArtifactSource(
                registry=f"http://127.0.0.1:{server.server_port}",
                repository="fixtures/sample",
                manifest_sha256=digest,
            )
        finally:
            server.shutdown()
            thread.join()
