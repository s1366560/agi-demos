import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

const panelSource = await readFile(
  new URL('../src/features/workspace/WorkspaceMembersPanel.tsx', import.meta.url),
  'utf8',
);
const dialogSource = await readFile(
  new URL('../src/features/workspace/WorkspaceSettingsDialog.tsx', import.meta.url),
  'utf8',
);
const appSource = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8');

test('workspace settings owns a separate authoritative member-management panel', () => {
  assert.match(dialogSource, /<WorkspaceMembersPanel/);
  assert.match(dialogSource, /members=\{members\}/);
  assert.match(dialogSource, /actorUserId=\{actorUserId\}/);
  assert.match(appSource, /members=\{dataset\.workspaceMembers\}/);
  assert.match(appSource, /actorUserId=\{auth\.user\?\.user_id \?\? ''\}/);
  assert.match(appSource, /onAddMember=\{addWorkspaceMemberFromDialog\}/);
  assert.match(appSource, /onUpdateMemberRole=\{updateWorkspaceMemberRoleFromDialog\}/);
  assert.match(appSource, /onRemoveMember=\{removeWorkspaceMemberFromDialog\}/);
});

test('workspace member controls preserve scope, user-id routing, confirmation, and feedback', () => {
  assert.match(panelSource, /canManageWorkspaceMembers/);
  assert.match(panelSource, /members\.status === 'loading'/);
  assert.match(panelSource, /members\.status === 'error'/);
  assert.match(panelSource, /members\.status === 'unavailable'/);
  assert.match(panelSource, /member\.user_email \?\? member\.user_id/);
  assert.match(panelSource, /onUpdateMemberRole\(\s*member\.user_id/);
  assert.match(panelSource, /onRemoveMember\(\s*member\.user_id/);
  assert.doesNotMatch(panelSource, /on(?:UpdateMemberRole|RemoveMember)\(member\.id/);
  assert.match(panelSource, /<AlertDialog\.Root/);
  assert.match(panelSource, /aria-live=/);
  assert.match(panelSource, /WorkspaceSettingsScopeChangedError/);
});
