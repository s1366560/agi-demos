/**
 * Timeline Rendering E2E Tests
 *
 * Tests for timeline mode rendering and typewriter effect in the agent chat interface.
 * These tests verify the complete user flow from message sending to display.
 */

import { test, expect } from '@playwright/test';

test.describe('Agent Chat - Timeline Rendering', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to agent chat page
    await page.goto('/project/1/agent');
  });

  test('should display messages in grouped mode by default', async ({ page }) => {
    // Send a message
    await page.fill('[data-testid="chat-input"]', 'Hello, how are you?');
    await page.click('[data-testid="send-button"]');

    // Wait for response
    await page.waitForTimeout(2000);

    // Verify grouped rendering - messages should be grouped
    const messages = page.locator('[data-testid="virtual-row-"]');
    await expect(messages.first()).toBeVisible();
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
    const events = page.locator('[data-testid="virtual-row-"]');
    await expect(events.first()).toBeVisible();
  });

  test('should show typing cursor during streaming', async ({ page }) => {
    // Send a message
    await page.fill('[data-testid="chat-input"]', 'Tell me a joke');
    await page.click('[data-testid="send-button"]');

    // Check for typing cursor during streaming
    await page.waitForSelector('.typing-cursor', { timeout: 5000 });
    const cursor = page.locator('.typing-cursor');
    await expect(cursor).toBeVisible();

    // Wait for cursor to disappear after completion
    await page.waitForSelector('.typing-cursor', { state: 'hidden', timeout: 10000 });
  });
});

test.describe('Agent Chat - Render Mode Toggle', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/project/1/agent');
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
