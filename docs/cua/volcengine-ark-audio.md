# Volcengine Ark audio input

The desktop client can use Ark through its OpenAI-compatible Chat API. The local
provider picker includes a **Volcengine Ark** preset with the official base URL
`https://ark.cn-beijing.volces.com/api/v3` and the environment reference
`ARK_API_KEY`. This preset does not activate a model or declare audio support.

## Configuration

1. Start the native client with `make -C agi-stack run-desktop`.
2. In Settings, add the Volcengine Ark preset. Keep the official base URL and
   environment credential reference, or enter a key through the existing
   encrypted application vault flow.
3. Discover models, enable an exact model ID that the Ark account has activated,
   and select the desired primary model.
4. Mark **Audio input** for that enabled model only after checking its declared
   input modalities. Save the model selection and declaration together.
5. Test the connection and complete an actual task. Model discovery lists the
   provider's catalog; it does not prove that the account has activated a model.

The local preset persists `provider_type: "openai_compatible"`. Environment
credentials are bound to the exact official HTTPS host, port and `/api/v3` path;
a custom or loopback endpoint cannot read `ARK_API_KEY` or `VOLCENGINE_API_KEY`
through this preset. A custom compatible service uses its own explicit credential
configuration instead.

Python cloud providers use the existing `volcengine` type and encrypted provider
credential storage. Their public configuration declares exact model IDs as:

```json
{
  "audio_input_models": ["doubao-seed-2-0-mini-260428"]
}
```

This object belongs in the provider API's `config` field. Desktop cloud Settings
maps the audio checkbox to that field and preserves the other supported public
provider parameters when saving or activating a provider. Local provider APIs
retain their existing top-level `audio_input_models` field.

Cloud audio declarations must belong to the exact configured model roster:
`llm_model`, `llm_small_model` and `secondary_models`. Cloud `allowed_models`
contains prefix filters; it is not that roster. Desktop model edits preserve
those filters while updating exact secondary IDs. Audio updates carry a public
configuration snapshot so existing tuning and retry settings are retained.

The Rust server's startup LLM uses explicit `AGISTACK_LLM_BASE_URL`,
`AGISTACK_LLM_MODEL` and `AGISTACK_LLM_API_KEY` settings. Its exact input-audio
model list is supplied through `AGISTACK_LLM_AUDIO_INPUT_MODELS` as a JSON array.
Provider CRUD metadata alone does not replace this startup execution route.

## Requests and limits

The maintained path uses Chat API `input_audio`, carrying raw Base64 bytes in
`input_audio.data` and the separate `format` field. Native recordings use WAV.
This path supports ordinary and streaming responses, including structured tool
actions. It does not infer audio support from a model name or destination URL.

Ark documents a 25 MB decoded-file limit for inline audio. Python rejects an
oversized Ark input before reading the artifact or issuing an HTTP request; the
recording remains available. Rust's generic compatible transport preserves the
provider's structured rejection. Audio requests cannot fall back to a text-only
model by silently removing their audio. The host's existing file-count and
aggregate-byte budgets also apply.

A full five-minute, 24 kHz stereo PCM16 WAV can exceed Ark's inline limit.
Recording and playback can succeed while model submission fails. Use a shorter
recording for inline understanding. Automatic Files API upload is not enabled:
it requires a separate remote-file retention, deletion and recovery lifecycle.

Official protocol and format reference:
[Ark audio understanding](https://console.volcengine.com/ark/region:cn-beijing/docs/audio-understanding).

## Validation on 2026-10-29

- Ark connectivity succeeded after correcting the active Clash rules: five
  exact Ark-related domains use `DIRECT`, and the remaining `MATCH` traffic
  continues through `GLOBAL`. Model discovery returned HTTP 200 with 138 models.
  The catalog explicitly declared audio input for
  `doubao-seed-2-0-mini-260428`.
- An actual text request to that model returned HTTP 200 and the requested
  canary text.
- An actual Chat API request containing a 361,200-byte, locally generated neutral
  WAV returned HTTP 200, the spoken phrase and 24 audio input tokens. This was a
  synthetic input fixture, not physical microphone, system or mixed capture.
- In the native desktop Settings UI, the operator created **Ark CUA QA1029**,
  selected the model and saved its explicit audio-input checkbox.
- Native system-audio recording captured an external `afplay` playback of a
  neutral fixture. Recording `33CFA8DA-EE25-4482-8C90-6C859A8991ED` saved artifact
  `cua-audio-d190b77e-0868-5b7e-a23b-8ff750143c55`: 484,096 bytes, 5.000 seconds,
  24 kHz stereo PCM16 WAV, file mode `0600`, peak 11,780 and RMS 2,177.92. Its
  receipt reported `source: system`, `status: saved` and
  `end_reason: duration_limit`. The later REPL output copy is the same capture,
  not a second recording.
- Ark transcribed the captured audio as “Violet seven. Computer use native
  acceptance violet.” The request prompt did not contain that phrase. The
  native preview played through five seconds. After a canonical cold restart,
  **Settings → Plugins** loaded the same recording and played through five
  seconds again. This verifies native system capture, model understanding,
  playback and persisted-recording recovery for this short fixture.
- Native microphone capture and playback completed. The initial quiet recording
  (artifact prefix `e36a7ccc`) contained 4.900 seconds in a 474,500-byte WAV while
  master output was muted; re-emitting it in the native App let Ark correctly
  identify silence. A separate microphone recording with master output
  temporarily set to 25% and unmuted saved artifact
  `cbbc35dd-039b-5c6f-b360-d33cd34ddac1`: 4.900 seconds, 474,500 bytes, peak 3,225
  and RMS 576.24. Capture and emission succeeded, but that task exhausted its
  round budget. A blind HTTP ASR control returned HTTP 200, “computer use native
  acceptance file seven” and 32 audio tokens. That HTTP result does not establish
  positive microphone understanding for that failed native task.
- A later Kimi microphone task saved a 20-second native recording as
  `cua-audio-3daa1137-313b-5572-9f4a-f28b7c0ab298`: 1,924,096 bytes, 24 kHz stereo
  PCM16 WAV, mode `0600`, peak 4,415 and RMS 521.25. The REPL copy
  `6643cab1-0a7a-4a33-9f80-a17f348a7335` is derived from that capture. Native
  preview playback was observed through the complete 20 seconds. At
  `ready_review`, the operator selected Ark and used `request_changes` solely
  to emit the owned `b.media`. The native App returned a transcript beginning
  “Acceptance file seven. Computer use native acceptance file seven”. This
  establishes native microphone audio input and a transcription result; the
  fixture's “violet” was recognized as “file”, so exact ASR accuracy is not
  established. The attempted independent Stop click used an expired AX target
  and did not execute; the receipt records an assistant stop instead.
- A separate 45-second-limit system recording passed independent native Stop.
  Fresh AX observed the independent button at `0:08`; another fresh observation
  and click stopped capture, and the UI saved the recording at `0:17` with the
  user-stopped label. The receipt reported `source: system`, `status: saved`,
  `end_reason: user_stopped` and artifact
  `cua-audio-cdc1dead-58b7-5435-946a-abb001c98731`: 1,651,456 bytes, 17.16 seconds,
  24 kHz stereo PCM16 WAV, mode `0600`, peak 11,706 and RMS 2,069.19. The original
  Promise completed normally and the task reached `ready_review`; the run was
  not cancelled. Native AX subsequently confirmed complete preview playback at
  17.16 seconds with the player back at its Play button.
- Native **Pause computer use** also stopped and saved an active system
  recording. Fresh AX observed eight seconds before a refreshed observation and
  click. The UI showed the saved recording at `0:15`, stopped due to computer-use
  pause, and exposed **Resume computer use**. Artifact
  `cua-audio-be2b2c80-656f-54ab-82ab-65f9dd2fcf81.wav` measured 1,497,856 bytes,
  15.56 seconds, 24 kHz stereo PCM16, mode `0600`, peak 11,704 and RMS 2,139.36.
  The next `audio.status` RPC returned
  `{retry_allowed:false,status:user_paused,type:computer_use_control}`. Native
  playback completed at 15.56 seconds. No Resume, old-cell retry or new start
  was issued. Pause stops native input/capture authority; a pure JavaScript
  timer can continue until the next native RPC returns the typed pause result.
  The operator later cancelled the Pause QA run with Stop response; it is not
  counted as a model-completed task.
- A native Kimi mixed-source recording continued the same Promise across two
  steps and saved artifact `2e15082c-060c-5856-a668-24d9a3b1cb71`: 5.000 seconds,
  484,096 bytes, peak 6,013 and RMS 1,077.37. The native player completed. While
  the run remained `ready_review`, the operator selected Ark and submitted
  `request_changes` to emit the owned `b.media` again. The actual native App
  transcribed “Tunes violet seven computer use native acceptance”. The run was
  then approved and completed. REPL output copies of the recordings are not
  counted as additional captures.
- A native browser task using the Ark mini model submitted incorrect plan/tool
  arguments. The pending run was cancelled through the native UI and is not
  counted as browser acceptance. A subsequent native Kimi task completed the
  guided local loopback CDP script after five exact approvals resumed its
  original cell Promise. Its actual output was
  `CDP_NATIVE_1029_OK | clicks=1 | trusted=true`, with a matching screenshot
  viewed by the operator and the run completed in the UI. This verifies that
  guided CDP path, not unguided autonomy or every browser provider.
- The documentation's `doubao-seed-2-1-lite-260915` example returned
  `ModelNotOpen` for the acceptance account. No additional service was activated.
- Focused desktop provider tests passed 81 cases, including a cross-language
  test of the actual Python response builder and model-declaration validation.
  Python provider/audio regression passed 183 cases. The earlier measured
  combined coverage for audio policy and artifact preparation was 95.50%; that
  measurement does not describe the expanded 183-test suite. The latest full
  sidecar regression passed 1,373 tests, with zero failures and three explicitly
  ignored interactive scenarios.
- HTTP adapter validation passed 59 tests including `finish_reason` diagnostics.
  Review-feedback UI validation passed 156 tests and both renderer/test
  TypeScript checks. These fixes were loaded by the canonical native restart.
- Python completion handling passed 297 tests after 25 new regressions, with
  96.67% coverage for the relevant helper. Known `length` and `content_filter`
  outcomes reject incomplete text, JSON and tool results through repair/retry
  paths without partial-response splicing. API reload preserved health,
  authenticated current-user access and the migration head. See
  [completion diagnostics](../../src/infrastructure/llm/completion_finish.py).

Three-source native capture and playback have now completed: system and mixed
played through five seconds, and microphone played through the full 20 seconds.
All three sources now have actual native model audio-input results, including the
20-second positive microphone result and the quiet microphone silence case.
The microphone transcription contained a word substitution. The earlier
combined task still failed after its first segment and subsequent round-budget
exhaustion; the successful individual checks do not change that run's result.

Independent native Stop passed on the separate system-audio task. The earlier
microphone AX click still remains an unsuccessful attempt. The 17.16-second
recording played completely; native computer-use Pause and playback of its
15.56-second saved recording also passed. Resume and other recording
failure/recovery paths remain to be verified. After physical tests, master output
was restored to the original 81.25% and muted state.

Cloud execution remains pending. Actual Python-cloud login and workspace
creation succeeded, but the first native task failed before a model call when
eager embedding-provider resolution left no graph runtime and therefore no five
prepared memory tools. The
[deferred graph initialization](../../src/configuration/factories.py) change
passed 428 tests; final API reload and native replay are still in progress.
Rust current-user identity repair passed 92 related tests and actual HTTP →
Electron projection → renderer decoding, but native login and CUA replay have
not yet passed. These results do not extend the local Ark audio acceptance to
either cloud route.

Locked Use preflight confirmed foreground mode, the installed inactive component
and the required native grants; cold restart retained no old lease. The scoped
release fix passed 42 distinct host/consent tests and preserves fresh Once
consent for enable. Version 2 of the concrete native lock draft remains
unapproved: there has been no enable, system lock or action-time user
confirmation. The current canonical launch is loading that fix; the actual
unlock/fixture/relock cycle remains pending.

Supplemental native understanding used `ready_review` feedback to emit owned
media in the original conversation. Completed build runs reject ordinary new
input, and saved-recording reads retain their conversation identity checks.
Ordinary local attachment upload returned HTTP 501 and is not claimed as a
supported input route.
The remaining Computer Use journeys are described in the
[current native acceptance update](computer-use-2026-10-29.md). The successful
source-specific checks do not establish the outstanding native outcomes.
