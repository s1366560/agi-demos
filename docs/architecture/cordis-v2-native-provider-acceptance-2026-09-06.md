# Cordis V2 native Provider acceptance — 2026-09-06

This is a scoped development acceptance record, not final Cordis V2 release approval.

Source revision: `7ce3ed019249146a0078eb5569ac517425cbd02e` on `codex/cordis-v2`.
Observed at: `2026-09-06T06:37:34.041947+00:00`.

The client was launched with `make -C agi-stack run-desktop` in a task-owned QA profile. All interactions used the real Electron UI and its managed Rust sidecar and Workspace Core.

## Verified native sequence

1. Added `Cordis Native Kimi QA` through the Provider wizard using only the `KIMI_API_KEY` environment-variable reference. No key value was printed or saved in this record.
2. The connection check and model discovery succeeded against the preset Kimi coding endpoint. Selected `kimi-for-coding`; the saved Provider became the default model route.
3. Created `Cordis Native Provider Acceptance` in `Cordis V2 Native QA`. The model invoked `submit_plan` and persisted a one-step plan.
4. Approved the plan with the read-only permission profile. The actual native execution returned exactly `NATIVE_CORDIS_V2_KIMI_OK`.
5. Approved the result. The run became completed. Reloaded the entire native window and reopened the conversation; the plan, model and completed response remained visible.
6. Reopened Provider settings, verified persistence, then disabled and re-enabled the QA Provider. It remains enabled.

Workspace: `b1b3b1ca-f11d-46de-b560-c25c440bb0dd`.
Conversation: `5ddc7915-d99a-5b03-b008-641527c7989a`.

## Evidence

The local external evidence directory is private (0700); text, screenshots and JSON are 0600. These local files are supporting evidence, not a public CI artifact.

- `/var/tmp/cordis-native-provider-gMde7Z/completed-after-reload.png` — SHA256 `79773915540ee34385aca6bd9060654c451d61cb414de9a64b8de287ea4b0e7b`
- `/var/tmp/cordis-native-provider-gMde7Z/completed-after-reload.txt` — SHA256 `7481d563a46b0cf6a3dcc1a3fbc93b9db594a86d612bdb1a84d82c6b1909e534`
- `/var/tmp/cordis-native-provider-gMde7Z/provider-restored.png` — SHA256 `acdb56cee3dbe5c93fbb897f6c3e55d5738f23eb94eb3e214ca28965130d5729`
- `/var/tmp/cordis-native-provider-gMde7Z/provider-restored.txt` — SHA256 `059c3d2f1a3e868746611ed275220b3b41b6c69953f9b7011f9afd99721ec553`

## Remaining gates

Provider deletion and another operation after the final disable-enable update were not exercised. This record does not claim full Provider CRUD, all-runtime parity, multi-plane ACK/NACK recovery, V1 retirement, or release promotion. Existing partial/degraded parity verdicts remain unchanged.
