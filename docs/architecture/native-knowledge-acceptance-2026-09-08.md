# Native knowledge acceptance evidence

The local knowledge journey passed in the real Electron client on September 8,
2026. It used the canonical `make -C agi-stack run-desktop` entry point, an isolated
application profile and workspace, the application credential vault, an existing
Kimi API connection, and an existing local embedding API. No models were installed
or downloaded. Production knowledge release remains closed; bidirectional cloud
synchronization is a separate pending acceptance journey.

Creation, extraction and indexing ran at `c83044800`. Restart and deletion ran at
`4c3602f2d`; subsequent `8cbaa616f` changes only parity source definitions. The
application retained the same isolated directories across restart. Its selected
scope was Northstar Labs / Desktop Client, authenticated as the local test user.
The qualification purpose remained local knowledge acceptance, without the new
explicit synchronization QA purpose.

## Observed native journey

| Operation | Observed result |
| --- | --- |
| Create and read | `NATIVE_KNOWLEDGE_20260908` was saved and listed as version 1. |
| Edit and read | Version 2 contained the isolated Chinese project/experiment example and `NATIVE_KNOWLEDGE_BODY_V2`. Both list and detail showed the saved content. |
| Provider connection | The native wizard verified Kimi, discovered its real model directory and saved `kimi-for-coding` using the existing environment credential. |
| Workspace creation | The native form created `Native Knowledge QA 20260908`; the extraction selector discovered that real Workspace Core record. |
| Explicit extraction | One confirmed operation applied version 2 on its first attempt. The persisted audit records `knowledge-extractor-v1`, `kimi-for-coding`, `submit_knowledge_projection`, input, structured output, rationale and 25,067 ms latency. |
| Text retrieval | The marker was absent before extraction and present afterward, with source version 2, change sequence 2 and audit attempt 1. |
| Entity/relationship retrieval | Four entities and four relationships were returned with the same source and audit references. |
| Embedding configuration | The native Provider model page explicitly declared the existing `bge-m3:latest` model for embeddings. A real API probe established 1,024 dimensions and configuration version 1. |
| Indexing and promotion | One confirmed index task completed for version 2. Coverage became 1/1; a separate confirmation promoted the build to the active index. |
| Semantic retrieval | An English question about responsibility and experiment recording returned the Chinese source with cosine similarity 0.5557. This verifies execution and provenance, not retrieval quality. |
| Restart | Local login, workspace, memory, applied extraction, embedding configuration, 1/1 coverage and the active build survived the canonical restart. The same semantic query returned the same source and displayed score. |
| Delete and stale result | Deleting the displayed version removed the test memory. Opening an earlier hit reported that its source version was unavailable; repeating semantic retrieval returned no records. |

The source memory was `11a9fd58-8e06-4dc4-8ce5-55de03c8eee7`, workspace
`9590ab5d-edf6-4e3c-9468-722e781e55db`, and index build
`f925512f-8954-4791-8435-b87cff11fb90`. These identify disposable QA records only.
Deletion was performed through the native interface. The audit was subsequently
inspected through a read-only SQLite connection; no database contents were edited.

## Issues found and corrected

- `492fc9e96` admits the generated native knowledge V1 capability only for its
  declared local surface. Previously the global capability parser rejected it,
  preventing native memory and Provider routes from opening.
- `f0f434c31` gives CRUD a generation-leased authenticated scope observation.
  Previously creating or opening a memory incorrectly called the forbidden
  `sync_status` operation in a local-only profile. The original controller failed
  the reproduction; 213 related tests passed after correction.
- `0e85d06f9` states that retrieval requires the current successfully extracted
  version and that saving does not automatically run processing or synchronization.
  The associated compiled UI/controller regression passed 24 tests.
- `4c3602f2d` moves canonical JSON into normal Sidecar dependencies. Tests had
  hidden this omission because the library was previously a dev dependency.
  The failing canonical build was followed by a successful normal binary check
  and successful canonical launch. Pending connector call sites still produce
  unused-code warnings at this intermediate baseline.

The macOS background window initially exposed updated accessibility content while
its screenshot retained an old loading frame. The application's existing
`focusMainWindow()` restoration path restored drawing after a clean restart.
No GPU flags or rendering workaround were added. Screenshots before restoration
are not visual acceptance evidence.

## Provider and release limits

The Ark connection and application-vault credential path passed native connection
and model-directory validation. Its listed legacy text embedding models rejected
actual embedding calls with `InvalidEndpointOrModel.NotFound`. The coding-plan
endpoint rejected the account's subscription; no subscription was changed. The
available vision embedding endpoint uses a different multimodal request/response
protocol, which this OpenAI-compatible embedding adapter does not implement.
Successful local embedding acceptance therefore uses the pre-existing local API.

The explicit native/cloud synchronization QA profiles and HTTP generation
preconditions are implemented, but their connector and UI journey remain pending.
This document does not approve production release, formal parity, packaged builds,
or the separate cloud/native automation deployment cutover.

## Local evidence artifacts

These files are local execution evidence, not portable CI artifacts:

- `/tmp/native-knowledge-crud-c83044800.txt` and `.jpg`
- `/tmp/native-knowledge-provider-c83044800.txt`
- `/tmp/native-knowledge-workspace-c83044800.txt`
- `/tmp/native-knowledge-processing-c83044800.txt` and `.jpg`
- `/tmp/native-knowledge-audit-c83044800.json`
- `/tmp/native-knowledge-entities-c83044800.txt`
- `/tmp/native-knowledge-relationships-c83044800.txt`
- `/tmp/native-knowledge-semantic-c83044800.txt` and `.jpg`
- `/tmp/native-knowledge-restart-4c3602f2d.txt` and `.jpg`
- `/tmp/native-knowledge-delete-4c3602f2d.txt` and `.jpg`
- `/tmp/native-knowledge-acceptance-c83044800.json` and `.log`
- `/tmp/native-knowledge-acceptance-4c3602f2d.json` and `.log`

GitNexus impact/change detection remained unavailable with `Transport closed`.
Source inspection, isolated regression tests, canonical builds and the native
journey provide the available evidence; no graph validation is claimed.
