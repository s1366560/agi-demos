"""Check the default SDK entry and the configurable Billing release use one contract."""

import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from memstack_plugin_sdk.pack import build

from plugins.business.billing.build import ROOT, build_release


def test_default_descriptor_matches_the_configurable_release():
    key = Ed25519PrivateKey.generate()
    spec = json.loads((ROOT / "package.json").read_bytes())
    plans = json.loads((ROOT / "plans.json").read_bytes())
    assert build(ROOT / "package.json", key) == build_release(
        plans, version=spec["version"], signer=key
    )
