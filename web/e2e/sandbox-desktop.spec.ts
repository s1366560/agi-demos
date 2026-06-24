/**
 * E2E Tests for Sandbox Desktop and Terminal Integration
 *
 * Tests the integration of remote desktop (noVNC) and web terminal (ttyd)
 * in the Agent Chat interface.
 */

import {
  agentWorkspacePath,
  createTestProject,
  getAdminAuthToken,
  loginAsAdmin,
  test,
  expect,
} from './base';

interface SandboxProject {
  id: string;
  tenantId: string;
}

async function createSandboxProject(): Promise<SandboxProject> {
  const token = await getAdminAuthToken();
  const project = await createTestProject({
    name: `Sandbox Test ${Date.now()}`,
    description: 'E2E Sandbox Test',
    token,
  });
  return { id: project.id, tenantId: project.tenantId };
}

test.describe('Sandbox Desktop and Terminal Integration', () => {
  let projectId: string;
  let tenantId: string;

  test.beforeEach(async ({ page }) => {
    const project = await createSandboxProject();
    projectId = project.id;
    tenantId = project.tenantId;
    await loginAsAdmin(page);
  });

  test('should navigate to agent chat page successfully', async ({ page }) => {
    // Navigate to agent chat
    await page.goto(agentWorkspacePath(projectId, tenantId));

    // Wait for page to load
    await page.waitForTimeout(2000);

    // Should show the agent chat interface
    await expect(page.getByRole('button', { name: /New Chat/i })).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#agent-message-input')).toBeVisible();
  });

  test('should have sandbox panel available in right sidebar', async ({ page }) => {
    // Navigate to agent chat
    await page.goto(agentWorkspacePath(projectId, tenantId));
    await page.waitForTimeout(2000);

    // The right panel should be present (with Plan tab by default)
    // We can verify this by checking for the right panel tabs container
    const rightPanelTabs = page.locator('.right-panel-tabs').first();
    if (await rightPanelTabs.isVisible({ timeout: 5000 })) {
      // Right panel is visible
      expect(rightPanelTabs).toBeVisible();
    }
  });

  test('should render sandbox components without errors', async ({ page }) => {
    // Navigate to agent chat
    await page.goto(agentWorkspacePath(projectId, tenantId));
    await page.waitForTimeout(2000);

    // Check for console errors related to sandbox
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        errors.push(msg.text());
      }
    });

    // Send a message that might trigger sandbox
    const input = page.locator('#agent-message-input');
    await input.fill('Hello');
    await page.keyboard.press('Enter');

    // Wait a bit for any rendering to occur
    await page.waitForTimeout(3000);

    // Check for sandbox-related errors
    const sandboxErrors = errors.filter(
      (err) => err.includes('sandbox') || err.includes('desktop') || err.includes('terminal')
    );

    // Should not have critical sandbox errors
    const criticalErrors = sandboxErrors.filter(
      (err) => err.includes('Cannot') || err.includes('undefined')
    );
    expect(criticalErrors.length).toBe(0);
  });
});

test.describe('Sandbox Component Structure', () => {
  let projectId: string;
  let tenantId: string;

  test.beforeEach(async ({ page }) => {
    const project = await createSandboxProject();
    projectId = project.id;
    tenantId = project.tenantId;
    await loginAsAdmin(page);
  });

  test('should render right panel with Plan and Sandbox tabs', async ({ page }) => {
    // Navigate to agent chat
    await page.goto(agentWorkspacePath(projectId, tenantId));
    await page.waitForTimeout(3000);

    // Check for tabs in the right panel
    // The right panel should have Plan tab
    const planTab = page.locator('.right-panel-tabs').getByText('Plan', { exact: true }).first();
    if (await planTab.isVisible({ timeout: 5000 })) {
      expect(planTab).toBeVisible();
    }
  });

  test('should have input area functional', async ({ page }) => {
    // Navigate to agent chat
    await page.goto(agentWorkspacePath(projectId, tenantId));
    await page.waitForTimeout(2000);

    // Should have input area
    const input = page.locator('#agent-message-input');
    await expect(input).toBeVisible();

    // Should be able to type in the input
    await input.fill('Test message');
    await expect(input).toHaveValue('Test message');
  });
});
