# Native model-visible tool contracts

Real Electron acceptance reached the configured Kimi provider, but repeated
`submit_plan` calls supplied `tasks[].description` instead of the required
`tasks[].content`. Source tracing found that the portable ReAct path advertised
only tool names. The HTTP action protocol allowed a generic input object, while
the concrete plan schema existed only in a UI instruction. Retrying the UI prompt
did not close the native acceptance gate.

The core now carries a static tool definition with its exact name, description and
input schema. ToolHost constructs definitions from the currently authorized name
roster, and the ReAct engine passes them through the typed LLM method. Missing
legacy metadata remains explicitly absent; a declared definition with a mismatched
name fails before the model decision rather than silently losing its schema.

The native profile, authorization, read-only automation and fan-out wrappers retain
the dispatching host's metadata. Profiled, metered and failover LLM wrappers carry
the typed definitions to OpenAI-compatible or Anthropic requests. Existing LLM
implementations can use a default method that serializes the definitions into the
model-visible goal. The structured AgentAction response protocol is unchanged;
this does not claim adoption of provider-native function-call response formats.

PlanMode declares its canonical schema at the tool definition: 1–50 tasks,
nonblank content, and an optional high/medium/low priority. Existing explicit
steps-based compatibility inputs remain supported, while `tasks[].description`
continues to be rejected. No semantic field guessing was added. Tools without a
declared schema are not represented as having a complete generic schema.

## Verification and scope

The new HTTP regression captures the actual outbound request and checks that the
full definition reaches the model. Native tests run the real ReAct engine through
Profiled, Metered and Failover wrappers, including a timed-out candidate and a
failed candidate, before OpenAI/Anthropic fixture endpoints return a structured
plan action. The real plan handler persists the resulting tasks. Authorization
tests use a stored run and its read-only authority to ensure forbidden tool
metadata is hidden. Other tests cover mismatched tool identity and strict plan
input rejection without writes.

The initial red compile (`/tmp/cordis-tool-contract-red.log`) established the
missing definition (E0432) and typed method (E0599). A later
new-test compile used an incorrect session enum variant; it was corrected to the
existing Finished variant. The focused native suite then passed. Combined core,
memory adapter, HTTP LLM adapter and full sidecar final run completed with
795 passed, zero failed/ignored and terminal exit 0, including 640 sidecar tests.
Post-fix native execution is recorded separately when complete; fixture HTTP
success is not native Provider acceptance.

The implementation lives in this checkout's `agi-stack` core, HTTP LLM adapter and
Desktop sidecar. It does not modify `third_party/avernet-bcs` or its cached build.
Small modules hold the new definition and moved LLM/plan implementations; the
existing large local runtime module shrinks.

GitNexus returned LOW for disambiguated trait symbols and UNKNOWN for unindexed
native symbols. Manual inspection found 43 related implementations, so the graph's
zero direct callers was not treated as zero impact. The regression covers the
actual native wrapper chain. Task-file rustfmt and diff checks passed. Strict
clippy did not pass: its 11 sidecar binary and 12 test diagnostics point to
pre-existing statements, including managed-store, MSRV and terminal code. They
were not changed as part of this focused repair and the strict gate is not
represented as passing.

Logs: `/tmp/cordis-native-tool-contracts.log` and
`/tmp/cordis-tool-contract-cargo-regression-final.log` (with terminal status in
`/tmp/cordis-tool-contract-cargo-regression-final.exit`), and
`/tmp/cordis-tool-contract-clippy.log`. Pre-fix native screenshots and
accessibility evidence are in `/var/tmp/cordis-final-native-7TENNl`.
