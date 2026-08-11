# Browser extension enterprise artifacts

Generate deterministic Chrome, Edge, Chromium, and Brave policy artifacts with:

```bash
AGISTACK_BROWSER_EXTENSION_ID=enbljdpbhdllbbkcjhccmbgpkfmcdkkl \
AGISTACK_BROWSER_EXTENSION_UPDATE_URL=https://<authorized-host>/update.xml \
AGISTACK_BROWSER_POLICY_OUTPUT_DIR=/absolute/output/directory \
pnpm enterprise:generate
```

The output includes:

- generic per-browser managed-policy JSON;
- Linux managed-policy JSON with the intended `/etc/.../policies/managed`
  installation location recorded in each artifact;
- a macOS `.mobileconfig` configuration profile for the four browser preference
  domains;
- a Windows current-user `.reg` policy artifact.

The generator refuses non-HTTPS update URLs and refuses to overwrite existing
artifacts. It validates the generated macOS and Linux documents against the
canonical contract before writing them. Generated policy force-installs the
pinned extension and allows only the `com.memstack.browserbridge` native host
through the native-messaging allowlist.

Generation is not deployment evidence. Windows HKCU policy import, macOS MDM
profile installation, and Linux managed-policy placement must each be verified
on their target OS before promotion.

`pnpm release:verify` accepts an externally produced CRX3 artifact and canonical
update manifest through environment variables. It validates the CRX3 signature,
public-key-derived extension ID, payload manifest version/key, update URL, and
update-manifest identity. It never creates or persists a CRX private key. A
missing externally provisioned CRX fails closed.

The extension `hello` response retains `protocolVersion: 1` and also advertises
the explicit supported interval `protocolMin: 1` through `protocolMax: 2` so a
host and extension can roll from N to N+1 without accepting a future-only peer.

## Accessibility promotion evidence

The extension's `options.html` and `sidepanel.html` entry points are part of the
release surface. Promotion still requires rendered evidence for both entry
points covering an automated axe scan, keyboard-only focus/order/activation,
and reduced-motion behavior. The cursor content-script reduced-motion unit test
does not satisfy those page-level checks. Until the two rendered entry points
produce that evidence, extension accessibility remains an explicit release
blocker rather than a passed gate.
