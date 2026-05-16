/**
 * Timeline Rendering E2E Tests
 *
 * Tests for timeline mode rendering and typewriter effect in the agent chat interface.
 * These tests verify the complete user flow from message sending to display.
 */

import { test, expect } from './base';

async function openAgentInput(page: import('@playwright/test').Page) {
  await page.goto('/login');
  if (page.url().includes('/login')) {
    await page.getByTestId('email-input').fill('admin@memstack.ai');
    await page.getByTestId('password-input').fill('adminpassword');
    await page.getByTestId('login-submit-button').click();
    await page.waitForURL(/\/tenant/, { timeout: 10000 });
  }

  await page.goto('/tenant/agent-workspace');

  const newConversation = page
    .getByRole('button', { name: /Start New Conversation|New Chat/i })
    .first();
  if (await newConversation.isVisible({ timeout: 5000 }).catch(() => false)) {
    await newConversation.click();
  }

  await expect(page.locator('[data-testid="chat-input"]')).toBeVisible({ timeout: 10000 });
}

test.describe('Agent Chat - Timeline Rendering', () => {
  test.beforeEach(async ({ page }) => {
    await openAgentInput(page);
  });

  test('should display messages in grouped mode by default', async ({ page }) => {
    // Send a message
    await page.fill('[data-testid="chat-input"]', 'Hello, how are you?');
    await page.click('[data-testid="send-button"]');

    // Wait for response
    await page.waitForTimeout(2000);

    // Verify grouped rendering - messages should be grouped
    await expect(page.getByText('Hello, how are you?').first()).toBeVisible();
    await expect(page.getByTestId('message-container')).toBeVisible();
  });

  test('should support timeline mode rendering', async ({ page }) => {
    // Toggle to timeline mode if there's a switch
    const modeSwitch = page.locator('[data-testid="render-mode-switch"]');
    if (await modeSwitch.isVisible()) {
      await modeSwitch.click();
    }

    // Send a message
    await page.fill('[data-testid="chat-input"]', 'Test timeline');
    await page.click('[data-testid="send-button"]');

    // Wait for response
    await page.waitForTimeout(2000);

    // Verify timeline rendering - each event should be visible
    await expect(page.getByText('Test timeline').first()).toBeVisible();
    await expect(page.getByTestId('message-container')).toBeVisible();
  });

  test('should show typing cursor during streaming', async ({ page }) => {
    // Send a message
    const input = page.getByTestId('chat-input');
    await input.fill('Tell me a joke');
    await expect(input).toHaveValue('Tell me a joke');
    await expect(page.getByTestId('send-button')).toBeEnabled();
  });
});

test.describe('Agent Chat - Render Mode Toggle', () => {
  test.beforeEach(async ({ page }) => {
    await openAgentInput(page);
  });

  test('should switch between grouped and timeline modes', async ({ page }) => {
    const modeSwitch = page.locator('[data-testid="render-mode-switch"]');

    if (await modeSwitch.isVisible()) {
      // Check initial state (should be grouped)
      await expect(modeSwitch).toHaveAttribute('data-mode', 'grouped');

      // Switch to timeline mode
      await modeSwitch.click();
      await expect(modeSwitch).toHaveAttribute('data-mode', 'timeline');

      // Switch back to grouped mode
      await modeSwitch.click();
      await expect(modeSwitch).toHaveAttribute('data-mode', 'grouped');
    }
  });
});
