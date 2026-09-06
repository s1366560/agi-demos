# Installed Bundle loader and deployment trust

`InstalledVerifiedBundleLoaderV2` returns the verified archive and its immutable bytes.
The existing marketplace publication service delegates to it, preserving the public
error type and codes. Scoped publication can use the same loader with an independently
owned database session instead of duplicating marketplace trust decisions.

Builtin loading requires the fixed repository source and exact id/version/digest before
parsing the repository archive. It uses repository trust, not a claim of marketplace
signature verification. Marketplace sources must have the exact logical locator derived
from id/version. The loader checks installed/revoked status, a configured registry set,
immutable OCI digests, current active permissions, Ed25519 signature, provenance, the
complete stored manifest and the requested identity. A logical source is never fetched
as an arbitrary URL. Marketplace archives are re-fetched from recorded OCI coordinates;
this implementation is not a persistent local archive store.

Deployment configuration uses JSON arrays:

- `PLUGIN_MARKETPLACE_TRUSTED_KEY_FILES`: operator-owned Ed25519 PEM public-key paths.
- `PLUGIN_MARKETPLACE_ALLOWED_REGISTRIES`: permitted OCI origins for Bundle publication.

The real application lifespan validates all keys and origins before database startup,
then installs immutable app-state values consumed by marketplace publishing. Empty
defaults add no signer trust and allow no external publication fetch. Invalid keys,
private keys and invalid registry URLs fail startup before partial trust state is set.
The publication allowlist does not add a new policy to marketplace catalog discovery or
the separate initial package installation fetch path.

The shared loader keeps an explicit `None` allowlist option for existing internal callers;
the production lifespan supplies an explicit set, including the empty set. Scoped startup
must likewise supply the configured set and must own per-load sessions. This batch does
not connect scoped Agent startup or claim persistent local archive materialization.
Concurrent governance revocation fencing, final V1 retirement and native acceptance
remain separate completion requirements.

Validation: final loader/router/trust regression passed 28 tests; configuration and
V2 startup regression passed 29 tests (overlapping trust cases). Generation/check and
contract completeness passed, as did Ruff and whitespace checks. Evidence with SHA-256
inventory: `/var/tmp/cordis-installed-bundle-trust-5tm4xwg2`.
