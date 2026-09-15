"""Serve the existing immutable QA package over the real OCI HTTP protocol."""

import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
archive = (ROOT / "marker.mspkg").read_bytes()
layer_digest = hashlib.sha256(archive).hexdigest()
manifest = json.dumps(
    {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": "application/vnd.memstack.plugin.v2",
        "layers": [
            {
                "mediaType": "application/vnd.memstack.plugin.bundle.v2+zip",
                "digest": "sha256:" + layer_digest,
                "size": len(archive),
            }
        ],
    },
    separators=(",", ":"),
).encode()
manifest_digest = hashlib.sha256(manifest).hexdigest()
routes = {
    "/v2/": (b"{}", "application/json", None),
    "/v2/qa/marker/manifests/sha256:" + manifest_digest: (
        manifest,
        "application/vnd.oci.image.manifest.v1+json",
        manifest_digest,
    ),
    "/v2/qa/marker/blobs/sha256:" + layer_digest: (
        archive,
        "application/vnd.memstack.plugin.bundle.v2+zip",
        layer_digest,
    ),
}


class RegistryHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = routes.get(self.path)
        body, media_type, digest = route or (b"", "application/octet-stream", None)
        self.send_response(200 if route else 404)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Docker-Distribution-Api-Version", "registry/2.0")
        if digest:
            self.send_header("Docker-Content-Digest", "sha256:" + digest)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), RegistryHandler)
metadata = {
    "registry": f"http://127.0.0.1:{server.server_port}",
    "repository": "qa/marker",
    "manifest_sha256": manifest_digest,
    "artifact_sha256": layer_digest,
    "artifact_bytes": len(archive),
}
(ROOT / "registry.json").write_text(json.dumps(metadata, indent=2) + "\n")
print(json.dumps(metadata), flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
