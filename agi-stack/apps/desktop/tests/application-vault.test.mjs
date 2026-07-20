import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const manifestUrl = new URL('../src-tauri/Cargo.toml', import.meta.url);
const trustedSessionUrl = new URL('../src-tauri/src/trusted_session.rs', import.meta.url);
const providerCredentialsUrl = new URL(
  '../src-tauri/src/local_runtime/provider_credentials.rs',
  import.meta.url,
);
const vaultUrl = new URL('../src-tauri/src/application_vault.rs', import.meta.url);

test('desktop credentials use the application vault without an operating-system keyring', () => {
  const manifest = readFileSync(manifestUrl, 'utf8');
  const credentialSources = [trustedSessionUrl, providerCredentialsUrl]
    .map((url) => readFileSync(url, 'utf8'))
    .join('\n');
  const vault = readFileSync(vaultUrl, 'utf8');

  assert.doesNotMatch(manifest, /^keyring\s*=/mu);
  assert.doesNotMatch(credentialSources, /keyring::|KEYRING_/u);
  assert.match(manifest, /^aes-gcm\s*=\s*\{[^\n]*features\s*=\s*\["zeroize"\]/mu);
  assert.match(vault, /Aes256Gcm/u);
  assert.match(vault, /aad: record_key\.as_bytes\(\)/u);
});
