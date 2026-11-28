"""Copy the release catalog's exact source artifacts into a staged Ray application."""

import argparse
import hashlib
import json
from pathlib import Path


def copy_module_artifacts(context: Path, application: Path) -> None:
    catalog = json.loads(
        (application / "shared/catalogs/plugin-module-catalog.v2.json").read_bytes()
    )
    context = context.resolve()
    application = application.resolve()
    for module in catalog["modules"]:
        scheme, separator, relative = module["artifact_source"].partition("://")
        if not separator or scheme not in {"repo+python", "repo+rust", "repo+typescript"}:
            raise ValueError(f"Unsupported module source for {module['module_ref']}")
        source = (context / relative).resolve()
        destination = (application / relative).resolve()
        if not source.is_relative_to(context) or not destination.is_relative_to(application):
            raise ValueError(f"Module source outside release context: {relative}")
        content = (destination if destination.is_file() else source).read_bytes()
        if f"sha256:{hashlib.sha256(content).hexdigest()}" != module["artifact_digest"]:
            raise ValueError(f"Module artifact digest mismatch: {relative}")
        if not destination.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("context", type=Path)
    parser.add_argument("application", type=Path)
    args = parser.parse_args()
    copy_module_artifacts(args.context, args.application)
