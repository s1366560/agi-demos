# Cordis V2 Web public view core

The browser requires an authenticated public view before its current distribution request can
stop using the workload-only endpoint. This batch adds projection and consumption primitives;
it does not change the production HTTP route or browser polling hook. The existing user-token
401 path therefore remains an open integration gate.

## Projection boundary

`project_web_public_view_v2` validates the source snapshot and pins Web module identity to the
generated trusted catalog. Repository metadata explicitly declares the entire configuration of
the three builtin Web modules public; unrecognized Web modules are rejected. Closed schemas
alone do not confer permission to disclose configuration.

The current bootstrap projects to six root entries and three modules. Non-Web configuration,
the source profile and entry identifiers, artifact provenance and signatures are excluded.
Non-root scopes, undeclared entry metadata and manifest permissions fail closed. Disabled
configuration is validated too. Validation errors use fixed messages without source values.

The wrapper contains only `schema_version`, `target`, `view_id`, and its independently digested
`snapshot`. Its identity binds the caller-supplied authority, public revision, and public digest.
It deliberately excludes the private source digest to avoid a private-value guessing oracle.
Callers must authenticate the user; this helper does not implement HTTP authentication or
tenant/project/session membership authorization.

## Consumer boundary

`WebPublicViewReconcilerV2` parses the strict wrapper, verifies the snapshot digest and Web/root
constraints, then serializes `replaceBaseline` operations. An unchanged view is skipped. A
failed candidate preserves the active generation. Closing drains pending operations and closes
the runtime. It does not call workload apply or produce global workload ACKs.

The future identity-aware hook must cancel stale fetches and close the old reconciler when the
authenticated identity changes. A view identifier is a cache identity, not an authorization
credential. Queued operations are drained rather than synchronously interrupted.

## Validation on 2026-09-06

- Python focused projection suite: 15 passed, 7 warnings.
- Web focused consumer suite: 8 passed, including real runtime application and candidate failure.
- Web `pnpm exec tsc --noEmit`: passed.
- Desktop `pnpm exec tsc -p tsconfig.test.json`: passed.
- Cross-language check: Python bootstrap projection passed the compiled TypeScript parser,
  loaded six entries in the real Web runtime, and closed successfully.
- Ruff and formatting checks passed after formatting the new TypeScript module.

No full-suite or browser/native acceptance is claimed for this batch. Remaining gates include
the authenticated HTTP route, browser polling and identity handoff, non-root scope authorization,
full-product acceptance, and final V1 retirement.
