# Cordis V2 Desktop multi-plane HTTP integration — 2026-09-06

Source revision: `55d4bfe172c6dcdcc1fa673cf81e659404f13e9b` on `codex/cordis-v2`.

The integration test passed against a new temporary PostgreSQL instance, the production FastAPI distribution and receipt router, a real Rust sidecar launched by `SidecarSupervisor`, and the real TypeScript renderer runtime and delivery reconciler. Python applied each candidate through its real runtime host and persisted its original receipt through the same repository operation used by production startup.

This is protocol and persistence evidence. It does not claim Electron native acceptance, a full product-profile rollout, Web browser distribution acceptance, or final V1 retirement.

## Verified behavior

The required roster was `python-api-v2`, `desktop-sidecar-v2`, and `desktop-renderer-v2`.

| Candidate | Python API | Sidecar | Renderer | Persisted publication |
| --- | --- | --- | --- | --- |
| Initial, before sidecar credential import | ACK | Missing | ACK | Reconciling; `ready_at` absent |
| Initial, after sidecar credential import | ACK | ACK | ACK | Ready |
| Unknown module targeting only sidecar | ACK | NACK | ACK | Degraded |
| Unknown module targeting only renderer | ACK | ACK | NACK | Degraded |

Fresh database sessions checked requested version/digest, each plane's actual receipt, retained applied identity on NACK, and the first candidate remaining the last globally ready publication. The renderer retained its previous active generation after its rejected candidate. Sidecar rejection did not prevent renderer delivery or ACK.

The production HTTP routes returned 401 for missing or invalid workload credentials and 403 when a valid sidecar credential attempted to submit a renderer receipt. Only `get_db` was overridden; the workload principal dependency was unchanged. Credentials traveled through process stdin and the private sidecar control pipe, not command arguments or logs.

## Execution and scope

- Result: **1 integration test passed in 68.37 seconds**, with 22 warnings.
- The test exercises three sequential candidates and the intermediate missing-sidecar state.
- PostgreSQL used actual migration upgrades `dc206dd13ac3`, `e91f4c7b2d60`, and `f43f5cd2fb21`. No `create_all`, revision stamping, or business database was used. This migration slice does not validate the historical full migration chain.
- The real clients use a minimal valid built-in profile. Target-specific unregistered modules produce real loader NACKs; receipts are not fabricated.
- The sidecar followed its normal polling schedule. Test cleanup stopped the child processes, removed their temporary directory, and removed the PostgreSQL container successfully.
- No production files changed in this test batch. Existing parity acceptance states were not promoted.

The reproducible test is `src/tests/integration/test_platform_plugin_desktop_multiplane_http.py`; its client runner is `agi-stack/apps/desktop/tests/support/renderer-multiplane-runner.mjs`. It requires an explicitly isolated `PLATFORM_PLUGIN_V2_POSTGRES_TEST_URL`, real `AGISTACK_REAL_SIDECAR` and `AGISTACK_REAL_WORKSPACE_CORE` binaries, and the compiled Desktop test runtime. Missing required configuration causes a skip, not an acceptance result.

## Local evidence

Private evidence directory: `/var/tmp/cordis-three-plane-http-iy3a24bk` (0700; files 0600).

- `pytest.log`: SHA256 `253f16966db20a7427d0532e3da326e77bb8dc6c012ab33a20bcde3e84eac021`.
- `isolated-run.log`: SHA256 `cba803a48ea376b6b13b26f3c5d7a3b845f081dff5c2b9cfeb9d9ecf7e23de80`.
- `reproduce-local.py`: SHA256 `983ee64aca6450f0f026e85ef1a10011f4e982da363c6c2fcb07960df2e1d4a4`.

The local reproduction script creates and destroys its own PostgreSQL container and redacts credential-shaped output before saving logs. These local artifacts are supporting evidence, not published CI results.
