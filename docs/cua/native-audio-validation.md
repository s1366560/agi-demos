# Native audio validation

On 2026-10-22, three separate MiniMax-backed native runs completed the public
REPL's inventory, start, status, stop/export and `nodeRepl.emitAudio` flow. Each
used its own generic step approval and native source-specific one-use consent,
with `max_duration_ms=3000`. The microphone WAV contained 2.900 seconds, system
audio 3.000 seconds and mixed audio 3.030 seconds; all were 24 kHz stereo PCM16
with nonzero samples. The system and mixed tests captured a separately generated
low-volume test tone through the actual capture sources. The stimulus file was
not used as a replacement for a recording.

Each run produced one inline audio output. Its exported and emitted WAV files
were byte-identical. Native playback was observed entering the playing state and
reaching the actual duration for all three sources, and the three QA runs were
marked complete after review. This provider had no declared audio-input model,
so these results establish recording, export and playback, not remote model audio
understanding. On 2026-10-27, a separate native run approved the generic wrapper
and exact microphone start step, then denied its independent native source
consent in the UI. The original pending cell was resumed once to reach that
consent; after denial there was no further start, stop, or reset call. A fresh
owner-scoped native status refresh returned no session, pending request, recording
or artifact for that conversation. The reviewed run completed. This verifies
application source-consent denial, not macOS TCC denial.
After the canonical native12 restart on 2026-10-23, the original three recording
receipts were opened through the native UI. Each player entered the playing
state and reached its full duration: 2.9, 3.0 and 3.03004 seconds respectively.
This verifies persisted playback across restart, not recovery of an active or
failed export.


On 2026-10-27, a separate mixed-source run used a 120000 ms capture limit.
The operator clicked the live card's Stop recording control at 9579 ms. A fresh
receipt reported `saved` and `user_stopped`; the original parent run remained
`running` and its native session remained active. The model then completed its
60000 ms wait and two subsequent status calls, both returning the same stopped
recording and artifact. Its later idempotent stop returned one inline audio
output without changing the recording ID, duration or stop reason.

The original and emitted WAV files were byte-identical at 875464 bytes, with
24 kHz stereo PCM16 data. The native player entered playback and returned to
stopped at the file's 9.07675-second duration. This checks independent UI recording
stop, continued parent execution, receipt retrieval and playback; it does not
stand in for pause/resume, device-change or failed-export recovery tests.

A second mixed-source run exercised the native Computer Use Pause and Resume
controls. Pause stopped and saved the sole recording at 7760 ms with
`end_reason=user_paused`. The session reported `paused` and `can_resume=true`;
Resume returned the same session to `idle`, rotated its input generation and
left the recording saved with the same ID, duration and stop reason. The original
parent run continued its wait, two new status calls and idempotent receipt
retrieval without starting another recording.

The original and emitted WAV files were byte-identical at 714496 bytes, with
24 kHz stereo PCM16 data and a decoded duration of 7.4 seconds. The native player
entered playback and reached that duration. The model could only report its
receipts; the operator separately performed and verified Resume in the native
UI before marking the run complete. These results do not cover device loss or
recovery of a failed export.

On 2026-10-27, another mixed-source run started with the built-in MacBook
microphone and MacBook speakers selected. During the one active recording, the
operator selected BenQ RD280UA DisplayPort output in macOS Sound settings. The
native recording stopped at 24302 ms and reported `saved`, `device_lost`,
`audio_device_changed`, `partial=true` and `can_retry_export=false`. The UI
displayed the device-disconnection and partial-recording messages. The model's
subsequent status and final status calls returned the same recording ID and
terminal receipt; no second recording or explicit stop was needed.

The interrupted capture preserved separate microphone and system WAVs. Both
were 24 kHz stereo PCM16; their emitted copies were byte-identical to the stored
artifacts. The native players entered playback and reached their respective
23.7- and 23.8-second ends. Output was restored to MacBook speakers with the
original 0.8125 volume and muted state. The run completed after native review,
and its independent observation session was revoked. This exercises an actual
output-route interruption; the built-in microphone remained selected throughout.

A separate system-audio recording exercised export failure and restart recovery.
After capture began, the operator created an empty directory at that recording's
previously absent WAV destination. Stop returned `failed`,
`cua_artifact_copy_failed` and `can_retry_export=true`, with no saved artifact.
The native UI retained this failed receipt after a full canonical application
restart. No recording restarted automatically.

The operator verified and removed only the owned empty fault directory, then
clicked Retry export in the native UI. The same recording ID, session, run,
start/end times and 98070 ms elapsed duration were preserved; its status changed
to `saved`, the error cleared and retry became unavailable. The resulting WAV
was 24 kHz stereo PCM16 with 2347680 frames, a decoded duration of 97.82 seconds
and SHA-256 `2e7fef3a0d55a523244488e443dfde704b3ac23283bbf049b1c1b9f0ca5b4d29`.
The native player entered playback and reached its full 1:37 end. This verifies
manual recovery of the failed export across restart and complete UI playback;
the system output remained muted, so audible output was not assessed.
