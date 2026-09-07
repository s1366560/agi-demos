# Authenticated Web view production integration

The Web generation hook now requests `/api/v1/platform-plugins/v2/web-view` through the kernel
HTTP client. The route uses the existing user API-key authentication dependency and returns
only the independently digested public Web view. The complete distribution and receipt routes
continue to require workload credentials. User identity binds the view identifier; the response
uses `Cache-Control: private, no-store`.

The production builtin route contribution registers the endpoint. Its artifact hash and the
generated protocol catalogs/bootstrap are regenerated from the changed source bytes. A missing
publication returns 404; invalid or unauthorized projection returns a fixed 503 response without
source configuration or validation diagnostics. Non-root views remain rejected until actual
scope membership authorization is implemented.

Token, user, tenant, and project changes synchronously abort old polling and revoke operation
admission. The identity coordinator hides the old generation, drains its reconciler, then starts
the replacement source. Public views use baseline replacement and never generate workload ACKs.
An already-started internal apply may finish before retirement, but cannot reopen UI or business
admission after its identity epoch changes. This is admission isolation, not physical cancellation
of arbitrary module work. Retired operations may still drain while a replacement root is usable.

## Evidence

- Five authenticated route tests use real stored users, API keys, and workload credentials, with
  only the test database dependency replaced. They cover both credential boundaries, two user
  identities, public payload parsing, missing publication, safe errors, and non-root refusal.
- Twenty focused Web tests cover real runtime loading, late HTTP responses, token/user/tenant/
  project handoff, an in-progress effect setup, old-operation draining, and cleanup failures.
- Web type checking and Desktop test TypeScript compilation passed.
- Full Web suite: 391 files and 3623 tests passed in 145.30 seconds; log:
  `/tmp/cordis-web-public-view-web-full.log`.
- `generate_plugin_protocol_v2.py --check` passed.
- Existing platform-plugin router regression: 51 passed, 23 warnings; log:
  `/tmp/cordis-web-view-router-regression.log`.
- After parity binding commit `5beef10e6`, the full Desktop suite passed: 4131 passed,
  2 skipped, 0 failed in 98.89 seconds; log: `/tmp/cordis-web-public-view-desktop-full.log`.
- Parity audit: `/var/tmp/cordis-web-public-view-parity-x4n4i5lk`; V2 has 66 accepted
  capabilities with 876 matching source hashes, V4 has 1 with 25 matching hashes. All existing
  states are unchanged. This verifies the existing declared scope only.
- Independent code review found no blocking issue within this boundary.

The Python V2 full run completed with 1545 passed and one failed in 1955.46 seconds. The failure
was the exact platform-plugin route inventory fixture missing the new Web endpoint. Its expected
path, method, response model, tags, and status-code list were updated without weakening the
comparison; all three route-contribution tests and five authenticated-view tests then passed.
The full suite has not been rerun after that fixture-only correction. Logs:
`/tmp/cordis-web-view-python-full.log` and `/tmp/cordis-web-view-route-table-final.log`.
The initial contract completeness scan also reported three pre-existing dynamic service
declarations in Rust Server's shared background worker module. Follow-up commit `667452b4f`
repaired those declarations; the main-checkout completeness scan now passes. This batch does not claim browser/native
end-to-end acceptance, tenant/project/session overlay completion, new Desktop parity acceptance,
or final V1 retirement. Existing Desktop parity capability source references do not cover this
new Web/backend authority chain and must not be cited as its acceptance evidence.
