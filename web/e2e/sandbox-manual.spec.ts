/**
 * Manual Sandbox UI Test
 */

import { test, expect } from '@playwright/test';

test('manual sandbox UI test', async ({ page }) => {
  // Set English locale
  await page.goto('http://localhost:3000');
  await page.evaluate(() => {
    localStorage.setItem('i18nextLng', 'en-US');
  });

  // Login
  console.log('Navigating to login page...');
  await page.goto('http://localhost:3000/login');

  // Take screenshot
  await page.screenshot({ path: 'test-screenshots/01-login.png' });

  await page.getByLabel(/Email/i).fill('admin@memstack.ai');
  await page.getByLabel(/Password/i).fill('adminpassword');
  await page.getByRole('button', { name: /Sign In/i }).click();

  // Wait for navigation - use more flexible wait
  console.log('Waiting for navigation after login...');
  await page.waitForURL(/\//, { timeout: 10000 });
  await page.waitForTimeout(2000);

  // Take screenshot after login
  await page.screenshot({ path: 'test-screenshots/02-after-login.png', fullPage: true });

  console.log('Current URL:', page.url());

  // Navigate to projects
  console.log('Navigating to projects...');
  const projectsLink = page.getByRole('link', { name: /Projects/i }).first();
  if (await projectsLink.isVisible({ timeout: 5000 })) {
    await projectsLink.click();
    await page.waitForTimeout(2000);
  }

  // Take screenshot
  await page.screenshot({ path: 'test-screenshots/03-projects.png', fullPage: true });

  // Get first project
  const projectCard = page.locator('a[href^="/project/"]').first();
  if (await projectCard.isVisible({ timeout: 5000 })) {
    const href = await projectCard.getAttribute('href');
    console.log('Found project href:', href);

    if (href) {
      // Navigate to project agent page
      const projectId = href.match(/\/project\/([^/]+)/)?.[1];
      if (projectId) {
        console.log('Project ID:', projectId);
        await page.goto(`http://localhost:3000/project/${projectId}/agent`);
        await page.waitForTimeout(3000);

        // Take screenshot
        await page.screenshot({ path: 'test-screenshots/04-agent-page.png', fullPage: true });

        // Check for input
        const input = page.locator('#agent-message-input');
        console.log('Input visible?', await input.isVisible({ timeout: 5000 }));
        console.log('New Chat button visible?', await page.getByRole('button', { name: /New Chat/i }).isVisible({ timeout: 5000 }));
      }
    }
  } else {
    console.log('No project found, creating one...');
    // Create project
    await page.getByRole('button', { name: /Create New Project/i }).click();
    await page.waitForTimeout(1000);
    await page.getByPlaceholder(/e.g. Finance Knowledge Base/i).fill(`Sandbox Test ${Date.now()}`);
    await page.getByPlaceholder(/Briefly describe the purpose/i).fill('E2E Sandbox Test');
    await page.getByRole('button', { name: /Create Project/i }).click();
    await page.waitForTimeout(3000);

    // Take screenshot
    await page.screenshot({ path: 'test-screenshots/05-after-create.png', fullPage: true });
  }

  // Keep page open for inspection
  console.log('Test complete. Page will stay open for 10 seconds for inspection.');
  await page.waitForTimeout(10000);
});
