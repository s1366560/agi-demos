import {
  API_BASE,
  createTestProject,
  expect,
  getAdminAuthToken,
  getFirstTenantId,
  loginAsAdmin,
  test,
} from './base';

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

  // Cross-session delete propagation: Core's outbox worker publishes
  // workspace_deleted to the legacy Redis stream, the store records
  // lastDeletedWorkspaceId, and useBlackboardLifecycle refetches the list so
  // the selection follows the remaining workspace.
  test('deleting the open workspace from another session switches to the remaining one', async ({
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

      // Warm-up: prove the live event channel is established before deleting,
      // otherwise the delete may race the subscription (events published before
      // the bridge's first read are not replayed) and make the test flaky.
      const warmUpTask = `e2e-warmup-${Date.now()}`;
      const taskResp = await fetch(`${API_BASE}/api/v1/workspaces/${workspaceA.id}/tasks`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ title: warmUpTask }),
      });
      expect(taskResp.status).toBe(201);
      await expect(page.getByText(warmUpTask).first()).toBeVisible({ timeout: 30_000 });

      await deleteWorkspaceViaApi(token, tenantId, projectId, workspaceA.id);

      await expect(page.locator('#workspace-select')).toHaveValue(workspaceB.id, {
        timeout: 30_000,
      });
      // The surface must follow the switch: the header shows B and the
      // agent-workspace link points at B (A would mean a stale surface).
      await expect(page.getByRole('link', { name: 'Open in Agent Workspace' })).toHaveAttribute(
        'href',
        new RegExp(`workspaceId=${workspaceB.id}`),
        { timeout: 20_000 }
      );
    } finally {
      await deleteWorkspaceViaApi(token, tenantId, projectId, workspaceA.id);
      await deleteWorkspaceViaApi(token, tenantId, projectId, workspaceB.id);
    }
  });

  test('deleting the open workspace via Settings lands on the workspace list', async ({ page }) => {
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
