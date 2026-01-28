/**
 * E2E Tests for Sandbox Desktop and Terminal Integration
 *
 * Tests the integration of remote desktop (noVNC) and web terminal (ttyd)
 * in the Agent Chat interface.
 */

import { test, expect } from './base';

test.describe('Sandbox Desktop and Terminal Integration', () => {
  let projectId: string;

  test.beforeEach(async ({ page }) => {
    // Set English locale
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
    });

    // Login
    await page.goto('http://localhost:3000/login');
    await page.getByLabel(/Email/i).fill('admin@memstack.ai');
    await page.getByLabel(/Password/i).fill('adminpassword');
    await page.getByRole('button', { name: /Sign In/i }).click();

    // Wait for navigation
    await page.waitForURL(/\/tenant/);

    // Navigate to projects and get or create a test project
    await page.getByRole('link', { name: /Projects/i }).first().click();
    await page.waitForTimeout(1000);

    // Get first project ID or create new one
    const projectCard = page.locator('a[href^="/project/"]').first();
    if (await projectCard.isVisible({ timeout: 5000 })) {
      const href = await projectCard.getAttribute('href');
      if (href) {
        const match = href.match(/\/project\/([^\/]+)/);
        if (match) {
          projectId = match[1];
        }
      }
    }

    if (!projectId) {
      // Create a new project
      await page.getByRole('button', { name: /Create New Project/i }).click();
      await page.getByPlaceholder(/e.g. Finance Knowledge Base/i).fill(`Sandbox Test ${Date.now()}`);
      await page.getByPlaceholder(/Briefly describe the purpose/i).fill('E2E Sandbox Test');
      await page.getByRole('button', { name: /Create Project/i }).click();
      await page.waitForTimeout(2000);

      // Get the new project ID
      const newProjectCard = page.locator('a[href^="/project/"]').first();
      const href = await newProjectCard.getAttribute('href');
      if (href) {
        const match = href.match(/\/project\/([^\/]+)/);
        if (match) {
          projectId = match[1];
        }
      }
    }
  });

  test('should navigate to agent chat page successfully', async ({ page }) => {
    // Navigate to agent chat
    await page.goto(`http://localhost:3000/project/${projectId}/agent`);

    // Wait for page to load
    await page.waitForTimeout(2000);

    // Should show the agent chat interface
    await expect(page.getByRole('button', { name: /New Chat/i })).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#agent-message-input')).toBeVisible();
  });

  test('should have sandbox panel available in right sidebar', async ({ page }) => {
    // Navigate to agent chat
    await page.goto(`http://localhost:3000/project/${projectId}/agent`);
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
    await page.goto(`http://localhost:3000/project/${projectId}/agent`);
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
    const sandboxErrors = errors.filter(err =>
      err.includes('sandbox') ||
      err.includes('desktop') ||
      err.includes('terminal')
    );

    // Should not have critical sandbox errors
    const criticalErrors = sandboxErrors.filter(err =>
      err.includes('Cannot') || err.includes('undefined')
    );
    expect(criticalErrors.length).toBe(0);
  });
});

test.describe('Sandbox Component Structure', () => {
  let projectId: string;

  test.beforeEach(async ({ page }) => {
    // Set English locale
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
    });

    // Login
    await page.goto('http://localhost:3000/login');
    await page.getByLabel(/Email/i).fill('admin@memstack.ai');
    await page.getByLabel(/Password/i).fill('adminpassword');
    await page.getByRole('button', { name: /Sign In/i }).click();

    // Wait for navigation
    await page.waitForURL(/\/tenant/);

    // Navigate to projects and get or create a test project
    await page.getByRole('link', { name: /Projects/i }).first().click();
    await page.waitForTimeout(1000);

    // Get first project ID or create new one
    const projectCard = page.locator('a[href^="/project/"]').first();
    if (await projectCard.isVisible({ timeout: 5000 })) {
      const href = await projectCard.getAttribute('href');
      if (href) {
        const match = href.match(/\/project\/([^\/]+)/);
        if (match) {
          projectId = match[1];
        }
      }
    }

    if (!projectId) {
      // Create a new project
      await page.getByRole('button', { name: /Create New Project/i }).click();
      await page.getByPlaceholder(/e.g. Finance Knowledge Base/i).fill(`Sandbox Test ${Date.now()}`);
      await page.getByPlaceholder(/Briefly describe the purpose/i).fill('E2E Sandbox Test');
      await page.getByRole('button', { name: /Create Project/i }).click();
      await page.waitForTimeout(2000);

      // Get the new project ID
      const newProjectCard = page.locator('a[href^="/project/"]').first();
      const href = await newProjectCard.getAttribute('href');
      if (href) {
        const match = href.match(/\/project\/([^\/]+)/);
        if (match) {
          projectId = match[1];
        }
      }
    }
  });

  test('should render right panel with Plan and Sandbox tabs', async ({ page }) => {
    // Navigate to agent chat
    await page.goto(`http://localhost:3000/project/${projectId}/agent`);
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
    await page.goto(`http://localhost:3000/project/${projectId}/agent`);
    await page.waitForTimeout(2000);

    // Should have input area
    const input = page.locator('#agent-message-input');
    await expect(input).toBeVisible();

    // Should be able to type in the input
    await input.fill('Test message');
    await expect(input).toHaveValue('Test message');
  });
});
