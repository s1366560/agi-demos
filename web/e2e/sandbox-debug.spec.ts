/**
 * Debug Sandbox UI Test
 */

import { test, expect } from '@playwright/test';

test('debug sandbox UI', async ({ page }) => {
  // Listen for console errors
  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.log('Browser console error:', msg.text());
    }
  });

  page.on('pageerror', error => {
    console.log('Page error:', error.message);
  });

  // Set English locale
  await page.goto('http://localhost:3000');
  await page.evaluate(() => {
    localStorage.setItem('i18nextLng', 'en-US');
  });

  // Login
  console.log('=== Login ===');
  await page.goto('http://localhost:3000/login');
  await page.getByLabel(/Email/i).fill('admin@memstack.ai');
  await page.getByLabel(/Password/i).fill('adminpassword');
  await page.getByRole('button', { name: /Sign In/i }).click();

  // Wait for navigation
  await page.waitForURL(/\//, { timeout: 10000 });
  await page.waitForTimeout(2000);
  console.log('Current URL after login:', page.url());

  // Check if token is stored
  const authStorage = await page.evaluate(() => localStorage.getItem('memstack-auth-storage'));
  console.log('Auth storage:', authStorage?.substring(0, 200) + '...');
  if (authStorage) {
    const parsed = JSON.parse(authStorage);
    console.log('Has token?', !!parsed.state?.token);
    console.log('Token (first 50 chars):', parsed.state?.token?.substring(0, 50));
  }

  // Navigate to projects
  console.log('=== Navigate to Projects ===');
  await page.getByRole('link', { name: /Projects/i }).first().click();
  await page.waitForTimeout(2000);

  // Get first project
  const projectCard = page.locator('a[href^="/project/"]').first();
  const href = await projectCard.getAttribute('href');
  console.log('Project href:', href);

  if (href) {
    const projectId = href.match(/\/project\/([^\/]+)/)?.[1];
    console.log('Project ID:', projectId);

    // Navigate to agent page WITHOUT conversation ID
    console.log('=== Navigate to Agent Page ===');
    await page.goto(`http://localhost:3000/project/${projectId}/agent`);

    // Wait longer for page to fully load and React to hydrate
    await page.waitForTimeout(5000);

    // Also wait for network to be idle
    try {
      await page.waitForLoadState('networkidle', { timeout: 5000 });
    } catch {
      // Ignore if networkidle timeout
    }

    console.log('Current URL:', page.url());

    // Check if token is still available after navigation
    const authStorage2 = await page.evaluate(() => localStorage.getItem('memstack-auth-storage'));
    console.log('Auth storage after navigation:', authStorage2?.substring(0, 100) + '...');

    // Check if getAuthToken works in browser context
    const tokenCheck = await page.evaluate(() => {
      const storage = localStorage.getItem('memstack-auth-storage');
      if (storage) {
        const parsed = JSON.parse(storage);
        return parsed.state?.token || parsed.token || null;
      }
      return null;
    });
    console.log('Token from evaluate:', tokenCheck?.substring(0, 50));

    // Take screenshot
    await page.screenshot({ path: 'test-screenshots/debug-01-agent-page.png', fullPage: true });

    // Check DOM elements
    console.log('=== Checking DOM Elements ===');

    // Check for input area
    const inputArea = page.locator('[data-testid="agent-input-area"]');
    const inputVisible = await inputArea.isVisible({ timeout: 5000 }).catch(() => false);
    console.log('Input area visible?', inputVisible);

    // Check for input by ID
    const inputById = page.locator('#agent-message-input');
    const inputByIdVisible = await inputById.isVisible({ timeout: 1000 }).catch(() => false);
    console.log('Input by ID visible?', inputByIdVisible);

    // Check for textarea
    const textarea = page.locator('textarea[name="agent-message"]');
    const textareaVisible = await textarea.isVisible({ timeout: 1000 }).catch(() => false);
    console.log('Textarea visible?', textareaVisible);

    // Check for New Chat button
    const newChatBtn = page.getByRole('button', { name: /New Chat/i });
    const newChatVisible = await newChatBtn.isVisible({ timeout: 5000 }).catch(() => false);
    console.log('New Chat button visible?', newChatVisible);

    // Get page content
    const bodyText = await page.locator('body').textContent();
    console.log('Page contains "Start a conversation"?', bodyText?.includes('Start a conversation'));

    // Check for InputArea component in DOM
    const inputAreaExists = await page.locator('.ant-input').count();
    console.log('Number of .ant-input elements:', inputAreaExists);

    // Check right panel
    const rightPanel = page.locator('.right-panel-tabs, [data-testid="sandbox-panel"]');
    const rightPanelVisible = await rightPanel.isVisible({ timeout: 1000 }).catch(() => false);
    console.log('Right panel visible?', rightPanelVisible);

    // List all buttons
    const buttons = await page.locator('button').all();
    console.log('Total buttons:', buttons.length);

    // Try to find and click New Chat button if it exists
    if (newChatVisible) {
      console.log('=== Clicking New Chat button ===');
      await newChatBtn.click();
      await page.waitForTimeout(2000);

      await page.screenshot({ path: 'test-screenshots/debug-02-after-new-chat.png', fullPage: true });

      // Check for input again
      const inputAfter = await inputById.isVisible({ timeout: 1000 }).catch(() => false);
      console.log('Input visible after New Chat?', inputAfter);
    }
  }

  console.log('=== Test Complete ===');
  await page.waitForTimeout(5000);
});
