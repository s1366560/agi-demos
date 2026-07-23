import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const manifest = readFileSync(new URL('../sidecar/Cargo.toml', import.meta.url), 'utf8');
const vaultSource = readFileSync(
  new URL('../sidecar/src/application_vault.rs', import.meta.url),
  'utf8',
);
const trustedSessionSource = readFileSync(
  new URL('../sidecar/src/trusted_session.rs', import.meta.url),
  'utf8',
);
const providerCredentialSource = readFileSync(
  new URL('../sidecar/src/local_runtime/provider_credentials.rs', import.meta.url),
  'utf8',
);
const migrationSource = readFileSync(
  new URL('../sidecar/src/data_migration.rs', import.meta.url),
  'utf8',
);

test('the Rust sidecar is the only desktop credential-vault authority', () => {
  const credentialSources = `${trustedSessionSource}\n${providerCredentialSource}`;

  assert.doesNotMatch(manifest, /^keyring\s*=/mu);
  assert.doesNotMatch(credentialSources, /keyring::|KEYRING_/u);
  assert.match(manifest, /^aes-gcm\s*=\s*\{[^\n]*features\s*=\s*\["zeroize"\]/mu);
  assert.match(vaultSource, /Aes256Gcm/u);
  assert.match(vaultSource, /aad: record_key\.as_bytes\(\)/u);
  assert.match(trustedSessionSource, /ApplicationCredentialVault/u);
  assert.match(providerCredentialSource, /ApplicationCredentialVault/u);
});

test('legacy vault and SQLite runtime state use atomic one-time migration', () => {
  assert.match(migrationSource, /credential-vault/u);
  assert.match(migrationSource, /backup::Backup/u);
  assert.match(migrationSource, /MIGRATION_MARKER/u);
  assert.match(migrationSource, /rename\(/u);
  assert.match(migrationSource, /set_private_file_permissions/u);
  assert.doesNotMatch(migrationSource, /overwrite\s*=\s*true/u);
});
