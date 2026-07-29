# Electron desktop client

Electron is the only native desktop shell. `electron-vite` builds the main, preload, and React
renderer processes into `out/`; a separate Rust executable provides the local runtime.

## Commands

Run these from the repository root:

```bash
make -C agi-stack run-desktop
make -C agi-stack desktop-electron-frontend
make -C agi-stack desktop-bundle
```

`make -C agi-stack run-desktop-electron` remains only as a compatibility alias for
`make -C agi-stack run-desktop`.

Any runtime source remaining under the legacy shell directory is migration residue, not a supported
runtime or build entry point. The canonical Make targets, CI, icons, and entitlement resources all
live outside that directory. No clean-checkout build depends on ignored local files under `build/`
except the sidecar staging directory created by `package:electron`.

## Security boundary

- The renderer runs with context isolation and Chromium sandboxing enabled.
- Node integration is disabled.
- The preload exposes only an allow-listed command bridge, never `ipcRenderer`.
- Electron starts the sidecar over private pipes and authenticates its one-time ready message with
  an HMAC challenge. The runtime port and launch token are never passed on the command line.
- Trusted sessions and Provider API keys are encrypted by the Rust AES-256-GCM application vault
  under the Electron user-data directory.
- New windows, external navigation, permission requests, and device-authorization URLs are
  constrained by the Electron main process.

## Runtime lifecycle

Electron owns sidecar startup, shutdown, capped crash restart, and command timeouts. On first start,
the sidecar migrates the legacy data directory with SQLite backup semantics and without overwriting
existing Electron data. Packaging stages the sidecar as an extra resource, signs it with the app,
and enables hardened runtime/notarization on macOS.

Local `package:electron` bundles deliberately clear the publish provider, do not contain
`app-update.yml`, and cannot contact the production update feed. Tag-release bundles retain the
structured GitHub provider metadata; the main process validates that metadata before starting
`electron-updater`. This distinction is controlled by the signed package contents, not a runtime
environment variable. The metadata contract alone does not prove that a packaged client fetched,
applied, or rolled back a real update.

## Production releases

Pushing a tag that exactly matches the desktop package version (`v0.1.0`, for example) runs
`.github/workflows/desktop-release.yml` on macOS, Windows, and Linux. Each runner builds its native
Rust sidecar and Electron artifacts without publishing them. No GitHub release draft is created
until all three jobs verify the packaged sidecar digest and update metadata; macOS additionally
verifies that the app and sidecar share a Developer ID authority and team identifier plus a stapled
notarization ticket, while Windows verifies Authenticode on both the installer and sidecar. The
verifier parses every `latest*.yml` file, requires its version to match `package.json` and the tag,
and checks every declared installer's root-relative name, exact size, and base64 SHA-512 digest.
Blockmaps are limited to `blockmap_structure_and_coverage_only`: the verifier checks the compressed
JSON contract, canonical checksum encoding, and declared chunk-size coverage, but does not
recompute chunk checksums or execute an updater. The resulting `desktop-release-evidence-v2`
records that scope, is explicitly limited to `package_artifacts_only`, and marks the release
`draft_only`.

The release workflow fails closed unless these repository secrets are configured:

- macOS: `MAC_CSC_LINK`, `MAC_CSC_KEY_PASSWORD`, `APPLE_API_KEY_BASE64`, `APPLE_API_KEY_ID`,
  `APPLE_API_ISSUER`, and `APPLE_TEAM_ID`
- Windows: `WIN_CSC_LINK`, `WIN_CSC_KEY_PASSWORD`, and `WIN_CSC_SHA1`

`APPLE_API_KEY_BASE64` must contain the base64-encoded bytes of the App Store Connect
`AuthKey_<key-id>.p8` private key. The macOS runner decodes it into a mode-`0600` temporary file and
exposes only that file path to the notarization process after dependencies, application code, and
the sidecar have already been built and staged. The file is removed in an `always()` cleanup step
after package-artifact verification. `WIN_CSC_SHA1` is the expected Authenticode
signing-certificate thumbprint; whitespace and case are normalized before the installer and sidecar
are compared.

The final workflow job creates or recovers the single exact-tag draft, uploads the verified
release-root assets, verifies the remote asset set, and then asserts that the release is still a
draft. A failed workflow can safely rerun against that draft only when the tag still resolves to the
workflow commit and every existing asset belongs to the exact verified local set. Unexpected
assets, an already-published release, or any non-draft final state fail closed. The workflow does
not promote the draft.

The draft includes `latest-mac.yml`, `latest.yml`, and `latest-linux.yml`, but their presence proves
only the package/update-metadata contract. Current tag CI does not install or launch the packages,
apply a real `electron-updater` update, or verify failed-update rollback. Wave 8 must add those
cross-platform native checks and a separate promotion gate; until then the release remains a draft.
