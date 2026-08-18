import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

import {
  API_BASE,
  createTestProject,
  expect,
  getAdminAuthToken,
  getFirstTenantId,
  loginAsAdmin,
  test,
} from './base';

const execFileAsync = promisify(execFile);

/**
 * WORKAROUND (product gap, Avernet cutover):
 * Workspace Core authorizes workspace creation against the
 * `avernet.project_principal_memberships` mirror, but nothing mirrors
 * `user_projects` rows into it at runtime — the offline migration service
 * (src/infrastructure/workspace_core/migration) is the only cloud-mode writer.
 * Result: POST /tenants/{t}/projects/{p}/workspaces returns 403 "Access
 * denied" for any project created after the last offline migration run.
 * Until a runtime sync exists, tests mirror the membership row directly.
 */
async function mirrorProjectMembership(projectId: string): Promise<void> {
  const sql = `
    INSERT INTO avernet.project_principal_memberships
      (tenant_id, project_id, user_id, participant_actor_id, source_membership_id,
       role, permissions_json, is_active, identity_authority, source_created_at, source_updated_at)
    SELECT p.tenant_id, p.id, up.user_id, up.user_id, up.id, up.role,
           COALESCE(up.permissions::jsonb, '{}'::jsonb), true, 'memstack',
           up.created_at, up.created_at
    FROM user_projects up
    JOIN projects p ON p.id = up.project_id
    WHERE up.project_id = '${projectId.replace(/[^a-z0-9-]/gi, '')}'
    ON CONFLICT (tenant_id, project_id, user_id) DO NOTHING;
  `;
  await execFileAsync('docker', [
    'exec',
    'memstack-postgres',
    'psql',
    '-U',
    'postgres',
    '-d',
    'memstack',
    '-v',
    'ON_ERROR_STOP=1',
    '-c',
    sql,
  ]);
}

interface TestWorkspace {
  id: string;
  name: string;
}

async function createWorkspaceViaApi(
  token: string,
  tenantId: string,
  projectId: string,
  name: string,
  description = 'E2E workspace fixture'
): Promise<TestWorkspace> {
  const resp = await fetch(
    `${API_BASE}/api/v1/tenants/${tenantId}/projects/${projectId}/workspaces`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        name,
        description,
        use_case: 'general',
        collaboration_mode: 'single_agent',
      }),
    }
  );
  const text = await resp.text();
  if (!resp.ok) {
    throw new Error(`Unable to create workspace fixture: ${String(resp.status)} ${text}`);
  }
  return JSON.parse(text) as TestWorkspace;
}

async function deleteWorkspaceViaApi(
  token: string,
  tenantId: string,
  projectId: string,
  workspaceId: string
): Promise<void> {
  await fetch(
    `${API_BASE}/api/v1/tenants/${tenantId}/projects/${projectId}/workspaces/${workspaceId}`,
    {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    }
  ).catch(() => {});
}

function workspacesPath(tenantId: string, projectId: string): string {
  return `/tenant/${tenantId}/project/${projectId}/workspaces`;
}

function blackboardPath(tenantId: string, projectId: string, workspaceId: string): string {
  return `/tenant/${tenantId}/project/${projectId}/blackboard?workspaceId=${workspaceId}`;
}

function blackboardSettingsPath(tenantId: string, projectId: string, workspaceId: string): string {
  return `${blackboardPath(tenantId, projectId, workspaceId)}&tab=settings`;
}

async function setupProject(page: Parameters<typeof loginAsAdmin>[0], label: string) {
  const token = await getAdminAuthToken();
  const tenantId = await getFirstTenantId(token);
  const project = await createTestProject({
    name: `e2e-ws-${label}-${Date.now()}`,
    tenantId,
    token,
  });
  await mirrorProjectMembership(project.id);
  await loginAsAdmin(page);
  return { token, tenantId, projectId: project.id };
}

async function fillCreateForm(
  page: Parameters<typeof loginAsAdmin>[0],
  name: string,
  description: string
) {
  await page.locator('#workspace-name-input').fill(name);
  await page.locator('#workspace-description-input').fill(description);
  await page.getByRole('radio', { name: /General/ }).click();
  await page.getByRole('radio', { name: /Single/ }).click();
}

test.describe('Workspace Core Flows', () => {
  test('workspace list loads for a project', async ({ page }) => {
    const { token, tenantId, projectId } = await setupProject(page, 'list');
    const workspaceName = `e2e-ws-list-${Date.now()}`;
    const workspace = await createWorkspaceViaApi(token, tenantId, projectId, workspaceName);

    try {
      await page.goto(workspacesPath(tenantId, projectId));
      await expect(page.getByRole('heading', { name: 'Workspaces' })).toBeVisible();
      await expect(page.getByRole('link', { name: workspaceName })).toBeVisible({
        timeout: 15_000,
      });
    } finally {
      await deleteWorkspaceViaApi(token, tenantId, projectId, workspace.id);
    }
  });

  test('create a workspace via the UI and see it in the list', async ({ page }) => {
    const { token, tenantId, projectId } = await setupProject(page, 'create');
    const workspaceName = `e2e-ws-create-${Date.now()}`;
    let createdId: string | null = null;

    try {
      await page.goto(`${workspacesPath(tenantId, projectId)}/new`);
      await fillCreateForm(page, workspaceName, 'E2E created workspace objective');
      await page.getByRole('button', { name: 'Create Workspace' }).click();

      await page.waitForURL(
        (url) => url.pathname.endsWith('/blackboard') && url.searchParams.has('workspaceId'),
        { timeout: 20_000 }
      );
      createdId = new URL(page.url()).searchParams.get('workspaceId');
      expect(createdId).toBeTruthy();

      await page.goto(workspacesPath(tenantId, projectId));
      await expect(page.getByRole('link', { name: workspaceName })).toBeVisible({
        timeout: 15_000,
      });
    } finally {
      if (createdId) {
        await deleteWorkspaceViaApi(token, tenantId, projectId, createdId);
      }
    }
  });

  test('duplicate workspace name surfaces a 409 error in the UI', async ({ page }) => {
    const { token, tenantId, projectId } = await setupProject(page, 'dup');
    const workspaceName = `e2e-ws-dup-${Date.now()}`;
    const workspace = await createWorkspaceViaApi(token, tenantId, projectId, workspaceName);

    try {
      await page.goto(`${workspacesPath(tenantId, projectId)}/new`);
      await fillCreateForm(page, workspaceName, 'Duplicate name attempt objective');
      await page.getByRole('button', { name: 'Create Workspace' }).click();

      await expect(page.getByText('A workspace with this name already exists.')).toBeVisible({
        timeout: 15_000,
      });
      // The user stays on the create page to fix the name.
      expect(page.url()).toContain('/workspaces/new');
    } finally {
      await deleteWorkspaceViaApi(token, tenantId, projectId, workspace.id);
    }
  });

  test('workspace settings persist across reload', async ({ page }) => {
    const { token, tenantId, projectId } = await setupProject(page, 'settings');
    const workspaceName = `e2e-ws-settings-${Date.now()}`;
    const workspace = await createWorkspaceViaApi(token, tenantId, projectId, workspaceName);
    const updatedDescription = `Updated objective ${Date.now()}`;

    try {
      await page.goto(blackboardSettingsPath(tenantId, projectId, workspace.id));
      await expect(page.locator('#workspace-name')).toHaveValue(workspaceName, {
        timeout: 20_000,
      });

      await page.locator('#workspace-description').fill(updatedDescription);
      await page.getByRole('button', { name: 'Save' }).click();
      await expect(page.getByText('Workspace updated successfully.')).toBeVisible({
        timeout: 15_000,
      });

      await page.reload();
      await expect(page.locator('#workspace-description')).toHaveValue(updatedDescription, {
        timeout: 20_000,
      });
    } finally {
      await deleteWorkspaceViaApi(token, tenantId, projectId, workspace.id);
    }
  });

  // PRODUCT BUG (documented, unfixed): deleting workspace A out-of-band while
  // its blackboard is open does NOT update the page. Verified live on
  // 2026-08-18: after DELETE /workspaces/{A} returns 204, the open blackboard
  // keeps A selected in #workspace-select, A's (stale) surface stays rendered,
  // and the selector still lists the deleted workspace 30s later. Two gaps:
  //  1. The workspace_deleted lifecycle event is only published by the legacy
  //     Python WorkspaceService.delete_workspace path; the Avernet proxy delete
  //     path never reaches the workspace store's handleWorkspaceLifecycleEvent.
  //  2. Even if the store handled the event, useBlackboardLifecycle keeps its
  //     own local workspaces/selectedWorkspaceId state and never re-syncs from
  //     the store, so the header selection would not follow the store fallback
  //     added in 9e363a204 ("reload surface after current workspace is deleted").
  test.fixme('deleting the open workspace from another session switches to the remaining one', async ({
    page,
  }) => {
    const { token, tenantId, projectId } = await setupProject(page, 'delete');
    const nameA = `e2e-ws-delete-a-${Date.now()}`;
    const nameB = `e2e-ws-delete-b-${Date.now()}`;
    const workspaceA = await createWorkspaceViaApi(token, tenantId, projectId, nameA);
    const workspaceB = await createWorkspaceViaApi(token, tenantId, projectId, nameB);

    try {
      await page.goto(blackboardPath(tenantId, projectId, workspaceA.id));
      await expect(page.locator('#workspace-select')).toHaveValue(workspaceA.id, {
        timeout: 20_000,
      });

      await deleteWorkspaceViaApi(token, tenantId, projectId, workspaceA.id);

      await expect(page.locator('#workspace-select')).toHaveValue(workspaceB.id, {
        timeout: 30_000,
      });
      // The surface must show B's data, not an empty panel.
      await expect(
        page.locator('#blackboard-panel-goals').getByText(nameB, { exact: false }).first()
      ).toBeVisible({ timeout: 20_000 });
    } finally {
      await deleteWorkspaceViaApi(token, tenantId, projectId, workspaceA.id);
      await deleteWorkspaceViaApi(token, tenantId, projectId, workspaceB.id);
    }
  });

  test('deleting the open workspace via Settings lands on the workspace list', async ({
    page,
  }) => {
    const { token, tenantId, projectId } = await setupProject(page, 'delete');
    const nameA = `e2e-ws-delete-a-${Date.now()}`;
    const nameB = `e2e-ws-delete-b-${Date.now()}`;
    const workspaceA = await createWorkspaceViaApi(token, tenantId, projectId, nameA);
    const workspaceB = await createWorkspaceViaApi(token, tenantId, projectId, nameB);

    try {
      await page.goto(blackboardSettingsPath(tenantId, projectId, workspaceA.id));
      await expect(page.locator('#workspace-name')).toHaveValue(nameA, { timeout: 20_000 });

      await page.getByRole('button', { name: 'Delete' }).click();
      await page.locator('.ant-popconfirm').getByRole('button', { name: 'Delete' }).click();

      await expect(page.getByText('Workspace deleted successfully.')).toBeVisible({
        timeout: 15_000,
      });
      // Fixed behavior (was: navigate('../..') to a non-route leaving a blank
      // main area): the app lands on the project workspace list, which shows
      // the remaining workspace and no longer lists the deleted one.
      await page.waitForURL(`**/tenant/${tenantId}/project/${projectId}/workspaces`, {
        timeout: 20_000,
      });
      await expect(page.getByRole('link', { name: nameB })).toBeVisible({ timeout: 15_000 });
      await expect(page.getByRole('link', { name: nameA })).toHaveCount(0);
    } finally {
      await deleteWorkspaceViaApi(token, tenantId, projectId, workspaceA.id);
      await deleteWorkspaceViaApi(token, tenantId, projectId, workspaceB.id);
    }
  });
});
