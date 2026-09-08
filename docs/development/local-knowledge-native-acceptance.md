# Local knowledge native acceptance

The fixed `memstack-local-knowledge-acceptance-v2` profile permits isolated local
implementation acceptance. It does not release the product's combined local
knowledge and bidirectional sync feature. The default bootstrap retains the
knowledge entry as disabled with `release_state: closed`.

## Host qualification

Use the existing unpackaged Electron QA launch configuration. Both directories
must be distinct, private, direct children of the host temporary directory with
an `agistack-desktop-qa-` prefix:

```sh
qa_temporary_root="${TMPDIR:-/tmp}"
qa_profile=$(mktemp -d "${qa_temporary_root%/}/agistack-desktop-qa-profile-XXXXXX")
qa_workspace=$(mktemp -d "${qa_temporary_root%/}/agistack-desktop-qa-workspace-XXXXXX")
AGISTACK_DESKTOP_QA_PROFILE_DIR="$qa_profile" \
AGISTACK_WORKSPACE_ROOT="$qa_workspace" \
make -C agi-stack run-desktop
```

Electron derives a fixed `local-knowledge-acceptance-v1` purpose after validating
both directories and the profile's `runtime` child. The purpose travels only in
the existing private initialization pipe. There is no renderer API, profile
selector, action list, credential, or additional enable flag. Legacy application
data migration is prohibited for this host qualification.

The Rust development build independently validates the directories, their private
permissions and identities, and the runtime/workspace binding. Generation loading
uses the compiled acceptance snapshot. Every knowledge admission and capability
observation verifies its exact profile ID, digest and local publication source. Replacing directories or
changing the workspace root invalidates the qualification. An acceptance config
without the qualified host cannot activate its service. Packaged Electron rejects
QA configuration; non-development Rust builds reject acceptance qualification.
Directory qualification currently supports Unix hosts; it is not Windows or signed
release acceptance evidence.

## Available acceptance scope

The observed capability remains `degraded`, with reason
`knowledge_local_acceptance_only`. Its action roster covers local CRUD, processing
configuration, extraction, indexing, text/semantic retrieval, entities and
relationships. Provider-dependent operations still require a real supported
Provider/model and vault binding. Extraction additionally requires a real authorized
Workspace Core workspace and policy. No model or workspace is fabricated.

All native sync endpoints and sync query variants remain closed in this profile.
Cloud enrollment, remote authorization, bidirectional conflict/recovery validation,
and signed/platform release evidence remain separate unfinished requirements.

Regenerate the default and acceptance snapshots through
`scripts/generate_plugin_protocol_v2.py`; never edit their digests or generated
catalogs. The acceptance contribution may change only the knowledge entry and
profile identity. Current source changes require normal artifact refresh, generated
contract checks, host/loader regressions and real Electron acceptance. Passing the
host/loader tests alone does not establish native UI acceptance.
