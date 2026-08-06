import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const desktopRoot = new URL('../', import.meta.url);

function source(relativePath) {
  return readFileSync(new URL(relativePath, desktopRoot), 'utf8');
}

test('Windows vault and migration paths enforce a protected current-user DACL', () => {
  const cargo = source('sidecar/Cargo.toml');
  const main = source('sidecar/src/main.rs');
  const policy = source('sidecar/src/private_file_permissions.rs');
  const vault = source('sidecar/src/application_vault.rs');
  const migration = source('sidecar/src/data_migration.rs');
  const releaseWorkflow = source('../../../.github/workflows/desktop-release.yml');

  assert.match(cargo, /target\.'cfg\(windows\)'\.dependencies/u);
  for (const feature of [
    'Win32_Foundation',
    'Win32_Security',
    'Win32_Security_Authorization',
    'Win32_System_SystemServices',
    'Win32_System_Threading',
  ]) {
    assert.match(cargo, new RegExp(feature, 'u'));
  }
  assert.match(main, /mod private_file_permissions;/u);
  assert.match(policy, /OpenProcessToken/u);
  assert.match(policy, /GetTokenInformation/u);
  assert.match(policy, /AddAccessAllowedAceEx/u);
  assert.match(policy, /ACCESS_ALLOWED_ACE_TYPE/u);
  assert.match(policy, /SetNamedSecurityInfoW/u);
  assert.match(policy, /PROTECTED_DACL_SECURITY_INFORMATION/u);
  assert.match(policy, /OBJECT_INHERIT_ACE/u);
  assert.match(policy, /CONTAINER_INHERIT_ACE/u);
  assert.match(policy, /windows_acl_contains_only_current_user/u);
  assert.match(policy, /windows_acl_rejects_missing_target/u);
  assert.match(vault, /set_private_(?:directory|file)_permissions/u);
  assert.match(vault, /private_file_permissions::/u);
  assert.match(vault, /windows_vault_files_use_current_user_only_acl/u);
  assert.match(migration, /set_private_(?:directory|file)_permissions/u);
  assert.match(migration, /private_file_permissions::/u);
  assert.match(migration, /migrated_windows_vault_files_use_current_user_only_acl/u);
  assert.doesNotMatch(
    `${vault}\n${migration}`,
    /#\[cfg\(not\(unix\)\)\][\s\S]{0,160}fn set_private_(?:directory|file)_permissions[\s\S]{0,120}Ok\(\(\)\)/u,
  );
  assert.match(releaseWorkflow, /platform: Windows[\s\S]*?os: windows-latest/u);
  assert.match(
    releaseWorkflow,
    /name: Test native Rust sidecar[\s\S]*?cargo test --manifest-path \.\.\/\.\.\/Cargo\.toml -p agistack-desktop-sidecar/u,
  );
});
