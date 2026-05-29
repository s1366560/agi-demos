"""Dump trusted darwinian_evolver snapshot pickles."""

from __future__ import annotations

import argparse
import importlib.util
import pickle
import sys
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument(
        "--driver",
        type=Path,
        default=Path(__file__).resolve().parent / "parrot_openrouter.py",
        help=(
            "Python driver module that defined organisms when the snapshot was "
            "created. Defaults to the sibling parrot_openrouter.py driver."
        ),
    )
    parser.add_argument(
        "--field",
        default=None,
        help="Organism attribute to display. Defaults to the first string field.",
    )
    parser.add_argument("--top", type=int, default=None, help="Show only top N by score.")
    parser.add_argument(
        "--i-trust-this-file",
        action="store_true",
        help="Required because pickle.loads executes arbitrary embedded code.",
    )
    args = parser.parse_args()

    if not args.snapshot.exists():
        sys.exit(f"snapshot not found: {args.snapshot}")

    if not args.i_trust_this_file:
        sys.exit(
            "refusing to unpickle: pickle.loads can execute arbitrary code. "
            "Only proceed for snapshots you created or fully trust, then re-run "
            f"with --i-trust-this-file.\n  file: {args.snapshot}"
        )

    print(
        f"WARNING: unpickling {args.snapshot}; only safe for snapshots you produced.",
        file=sys.stderr,
    )
    class_map = _load_driver_classes(args.driver) if args.driver else {}
    outer = _trusted_loads(args.snapshot.read_bytes(), class_map=class_map)
    if not isinstance(outer, dict) or "population_snapshot" not in outer:
        sys.exit("not a darwinian-evolver snapshot (missing population_snapshot)")

    inner = _trusted_loads(outer["population_snapshot"], class_map=class_map)
    pairs = inner["organisms"]
    ranked = sorted(pairs, key=lambda pair: getattr(pair[1], "score", 0) or 0, reverse=True)
    if args.top:
        ranked = ranked[: args.top]

    print(f"# organisms: {len(pairs)}\n")
    for index, (organism, result) in enumerate(ranked):
        score = getattr(result, "score", float("nan"))
        print(f"=== rank {index} score={score:.3f} ===")
        field = args.field or _first_string_field(organism)
        value = getattr(organism, field, None) if field else None
        if value is None:
            print(f"  (no string field; organism fields: {list(vars(organism).keys())})")
            print()
            continue
        print(f"  {field} ({len(value)} chars):")
        for line in value.splitlines()[:30]:
            print(f"    {line}")
        print()
    return 0


def _first_string_field(organism: object) -> str | None:
    for key, value in vars(organism).items():
        if isinstance(value, str) and not key.startswith("_") and key != "id":
            return key
    return None


def _load_driver_classes(driver_path: Path) -> dict[str, type[object]]:
    if not driver_path.exists():
        return {}

    module = _load_module_from_path(driver_path)
    classes: dict[str, type[object]] = {}
    for value in vars(module).values():
        if isinstance(value, type):
            classes[value.__name__] = value
    return classes


def _load_module_from_path(path: Path) -> ModuleType:
    module_name = f"darwinian_evolver_snapshot_driver_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load snapshot driver: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _trusted_loads(payload: bytes, *, class_map: dict[str, type[object]]) -> object:
    return _SnapshotUnpickler(BytesIO(payload), class_map=class_map).load()


class _SnapshotUnpickler(pickle.Unpickler):
    def __init__(self, file: BytesIO, *, class_map: dict[str, type[object]]) -> None:
        super().__init__(file)
        self._class_map = class_map

    def find_class(self, module: str, name: str) -> object:
        if module == "__main__" and name in self._class_map:
            return self._class_map[name]
        return super().find_class(module, name)


if __name__ == "__main__":
    sys.exit(main())
