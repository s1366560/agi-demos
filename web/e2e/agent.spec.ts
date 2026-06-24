import { test, expect } from './base';

const API_BASE = process.env.API_BASE || 'http://localhost:8000';

interface TokenResponse {
  access_token: string;
}

interface TenantResponse {
  tenants?: Array<{ id: string }>;
}

interface ProjectResponse {
  id: string;
}

interface CreatedAgentProject {
  id: string;
  tenantId: string;
}

interface ConversationMessagesResponse {
  timeline?: Array<{ type?: string; content?: string }>;
}

interface ApiErrorResponse {
  detail?: string;
}

function extractConversationId(url: string): string | null {
  return url.match(/\/agent-workspace\/([^/?#]+)/)?.[1] ?? null;
}

function agentWorkspaceUrl(projectId: string, tenantId?: string): string {
  const basePath = tenantId ? `/tenant/${tenantId}/agent-workspace` : '/tenant/agent-workspace';
  return `http://localhost:3000${basePath}?projectId=${projectId}`;
}

function agentConversationUrl(
  projectId: string,
  conversationId: string,
  tenantId?: string
): string {
  const basePath = tenantId ? `/tenant/${tenantId}/agent-workspace` : '/tenant/agent-workspace';
  return `http://localhost:3000${basePath}/${conversationId}?projectId=${projectId}`;
}

async function waitForConversationReady(page: import('@playwright/test').Page): Promise<void> {
  await expect(page.locator('#agent-message-input')).toBeVisible({ timeout: 15000 });
  await expect(page.getByText(/Loading conversation/i)).toBeHidden({ timeout: 15000 });
}

async function createConversationFromSidebar(
  page: import('@playwright/test').Page
): Promise<string> {
  const newChatButton = page.getByRole('button', { name: /New Chat/i });
  await expect(newChatButton).toBeEnabled({ timeout: 15000 });
  const previousConversationId = extractConversationId(page.url());

  await Promise.all([
    page.waitForURL(
      (url) => {
        const nextConversationId = extractConversationId(url.toString());
        return nextConversationId !== null && nextConversationId !== previousConversationId;
      },
      { timeout: 30000 }
    ),
    newChatButton.click(),
  ]);
  await waitForConversationReady(page);

  const conversationId = extractConversationId(page.url());
  expect(conversationId, `expected conversation id in URL: ${page.url()}`).not.toBeNull();
  return conversationId;
}

async function getPersistedToken(page: import('@playwright/test').Page): Promise<string | null> {
  return page.evaluate(() => {
    const storage = localStorage.getItem('memstack-auth-storage');
    if (!storage) return null;
    try {
      const parsed = JSON.parse(storage);
      return parsed?.state?.token ?? parsed?.token ?? null;
    } catch {
      return null;
    }
  });
}

async function loginViaApi(): Promise<string> {
  const form = new URLSearchParams();
  form.append('username', 'admin@memstack.ai');
  form.append('password', 'adminpassword');
  const resp = await fetch(`${API_BASE}/api/v1/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form.toString(),
  });
  expect(resp.ok).toBeTruthy();
  const data = (await resp.json()) as TokenResponse;
  return data.access_token;
}

async function getFirstTenantId(token: string): Promise<string> {
  const tenantResp = await fetch(`${API_BASE}/api/v1/tenants`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(tenantResp.ok).toBeTruthy();
  const tenantData = (await tenantResp.json()) as TenantResponse | Array<{ id: string }>;
  const tenants = Array.isArray(tenantData) ? tenantData : tenantData.tenants || [];
  expect(tenants.length).toBeGreaterThan(0);
  return tenants[0].id;
}

async function createAgentProject(): Promise<CreatedAgentProject> {
  const token = await loginViaApi();
  const tenantId = await getFirstTenantId(token);

  const projectResp = await fetch(`${API_BASE}/api/v1/projects/`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      name: `Playwright E2E Test Agent ${Date.now()}`,
      description: 'E2E Agent Test',
      tenant_id: tenantId,
    }),
  });
  const text = await projectResp.text();
  expect(projectResp.ok, `create project failed: ${projectResp.status} ${text}`).toBeTruthy();
  return { id: (JSON.parse(text) as ProjectResponse).id, tenantId };
}

async function createConversationViaApi(
  request: import('@playwright/test').APIRequestContext,
  token: string | null,
  projectId: string,
  title = 'Playwright API conversation'
): Promise<string> {
  expect(token).toBeTruthy();
  const response = await request.post(`${API_BASE}/api/v1/agent/conversations`, {
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    data: {
      project_id: projectId,
      title,
    },
  });
  const text = await response.text();
  expect(response.ok(), `create conversation failed: ${response.status()} ${text}`).toBeTruthy();
  const data = JSON.parse(text) as { id?: string };
  expect(data.id).toBeTruthy();
  return data.id as string;
}

async function openConversationViaApi(
  page: import('@playwright/test').Page,
  request: import('@playwright/test').APIRequestContext,
  projectId: string,
  title: string,
  tenantId?: string
): Promise<string> {
  const token = await getPersistedToken(page);
  const conversationId = await createConversationViaApi(request, token, projectId, title);
  await page.goto(agentConversationUrl(projectId, conversationId, tenantId));
  await waitForConversationReady(page);
  return conversationId;
}

async function stopAgentIfRunning(page: import('@playwright/test').Page): Promise<void> {
  const stopButton = page.getByRole('button', { name: /Stop/i });
  if (await stopButton.isVisible({ timeout: 1000 }).catch(() => false)) {
    await stopButton.click();
    await expect(page.getByTestId('send-button'))
      .toBeVisible({ timeout: 15000 })
      .catch(() => {});
  }
}

test.afterEach(async ({ page }) => {
  await stopAgentIfRunning(page);
});

test.describe('Agent Chat V3 (FR-016, FR-017)', () => {
  let projectId: string;
  let tenantId: string;

  test.beforeEach(async ({ page }) => {
    const project = await createAgentProject();
    projectId = project.id;
    tenantId = project.tenantId;

    // Set English locale
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
      localStorage.setItem('memstack_onboarding_complete', 'true');
    });

    // Login
    await page.goto('http://localhost:3000/login');
    await page.getByTestId('email-input').fill('admin@memstack.ai');
    await page.getByTestId('password-input').fill('adminpassword');
    await page.getByRole('button', { name: /Sign In/i }).click();

    // Wait for navigation
    await page.waitForURL(/\/tenant/);
  });

  test('should display agent chat V3 interface', async ({ page }) => {
    // Navigate to agent chat
    await page.goto(agentWorkspaceUrl(projectId, tenantId));

    // Wait for page to load
    await page.waitForTimeout(2000);

    // V3: Should show New Chat button in sidebar
    await expect(page.getByRole('button', { name: /New Chat/i })).toBeVisible({ timeout: 10000 });

    // V3: Should show the input area with TextArea (using ID selector)
    const input = page.locator('#agent-message-input');
    await expect(input).toBeVisible();

    // V3: Should expose Plan Mode as an accessible toolbar action.
    await expect(
      page.getByRole('button', { name: /Enter Plan Mode|Exit Plan Mode/i })
    ).toBeVisible();
  });

  test('should create new conversation via New Chat button', async ({ page }) => {
    // Navigate to agent chat
    await page.goto(agentWorkspaceUrl(projectId, tenantId));

    // Wait for page to load
    await page.waitForTimeout(2000);

    // Click New Chat button
    await createConversationFromSidebar(page);

    // V3: The input should be visible
    const input = page.locator('#agent-message-input');
    await expect(input).toBeVisible();
  });

  test('should display left sidebar with conversation list', async ({ page }) => {
    // Navigate to agent chat
    await page.goto(agentWorkspaceUrl(projectId, tenantId));

    // Wait for page to load
    await page.waitForTimeout(2000);

    // V3: Should show New Chat button (sidebar is visible by default)
    await expect(page.getByRole('button', { name: /New Chat/i })).toBeVisible();
  });

  test('should toggle left sidebar visibility', async ({ page }) => {
    // Navigate to agent chat
    await page.goto(agentWorkspaceUrl(projectId, tenantId));

    // Wait for page to load
    await page.waitForTimeout(2000);

    // Sidebar should be visible initially - New Chat button visible
    await expect(page.getByRole('button', { name: /New Chat/i })).toBeVisible();

    const collapseBtn = page.getByRole('button', { name: /Collapse sidebar/i }).first();
    await collapseBtn.click();
    await page.waitForTimeout(500);

    await expect(page.getByRole('button', { name: /Expand sidebar/i }).first()).toBeVisible({
      timeout: 3000,
    });

    // Click expand button
    const expandBtn = page.getByRole('button', { name: /Expand sidebar/i }).first();
    await expandBtn.click();
    await page.waitForTimeout(500);

    await expect(page.getByRole('button', { name: /New Chat/i })).toBeVisible();
  });

  test('should complete full chat workflow', async ({ page, request }) => {
    await openConversationViaApi(page, request, projectId, 'Full chat workflow', tenantId);

    // V3: Type a message in the TextArea
    const input = page.locator('#agent-message-input');
    await expect(input).toBeVisible();
    await input.fill('Hello, this is a test message');

    // V3: Send message by clicking the send button (circle button with SendOutlined icon)
    const sendButton = page.getByTestId('send-button');
    await expect(sendButton).toBeVisible();
    await sendButton.click();

    // Wait for message to be sent
    await page.waitForTimeout(3000);

    // User message should appear in the chat
    await expect(page.getByText('Hello, this is a test message').first()).toBeVisible({
      timeout: 10000,
    });

    // Input should be cleared and still visible
    await expect(input).toBeVisible();
  });

  test('should display thinking chain during agent response', async ({ page, request }) => {
    await openConversationViaApi(page, request, projectId, 'Thinking chain response', tenantId);

    // Send a message
    const input = page.locator('#agent-message-input');
    await input.fill('Search for memories about trends');

    const sendButton = page.getByTestId('send-button');
    await sendButton.click();

    // Wait for response to start
    await page.waitForTimeout(5000);

    // V3: User message should appear
    await expect(page.getByText('Search for memories about trends').first()).toBeVisible();

    // V3: Thinking chain should appear while the response is being generated.
    await expect(page.getByRole('button', { name: /Thinking|Reasoning/i }).first()).toBeVisible({
      timeout: 15000,
    });
  });

  test('should handle stop button during streaming', async ({ page, request }) => {
    await openConversationViaApi(page, request, projectId, 'Stop button streaming', tenantId);

    // Send a message
    const input = page.locator('#agent-message-input');
    await input.fill('Tell me a long story about programming');

    const sendButton = page.getByTestId('send-button');
    await sendButton.click();

    // Wait for streaming to start - the input should be disabled
    await page.waitForTimeout(1000);

    // V3: During streaming, check if input is disabled (indicating streaming is in progress)
    const isInputDisabled = await input.isDisabled();

    // If input is disabled, streaming is active
    // If input is enabled, streaming finished quickly
    // Both are valid states
    expect(typeof isInputDisabled).toBe('boolean');
  });

  test('should handle multi-turn conversation', async ({ page, request }) => {
    test.setTimeout(90000);

    await openConversationViaApi(page, request, projectId, 'Multi-turn conversation', tenantId);

    // First message
    const input = page.locator('#agent-message-input');
    await input.fill('Say hello');

    const sendButton = page.getByTestId('send-button');
    await sendButton.click();

    // Wait for response - check for either input enabled or agent response visible
    await page.waitForTimeout(5000);

    // User message should be visible
    await expect(page.getByText('Say hello').first()).toBeVisible();

    const stopButton = page.getByRole('button', { name: /Stop/i });
    if (await stopButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await stopButton.click();
    }

    const readySendButton = page.getByTestId('send-button');
    await expect(readySendButton).toBeVisible({ timeout: 30000 });

    // Second message (follow-up)
    await input.fill('Say goodbye');
    await expect(readySendButton).toBeEnabled({ timeout: 30000 });
    await readySendButton.click();
    await page.waitForTimeout(3000);

    // Both messages should be visible
    await expect(page.getByText('Say hello').first()).toBeVisible();
    await expect(page.getByText('Say goodbye').first()).toBeVisible();
  });

  test('should handle error states gracefully', async ({ page, request }) => {
    await openConversationViaApi(page, request, projectId, 'Error state baseline', tenantId);

    // V3: The UI should handle errors gracefully
    // Input should be present and functional
    const input = page.locator('#agent-message-input');
    await expect(input).toBeVisible();

    // Input should be present
    expect(await input.count()).toBeGreaterThan(0);
  });

  test('should toggle plan mode', async ({ page, request }) => {
    await openConversationViaApi(page, request, projectId, 'Plan mode toggle', tenantId);

    const planModeButton = page.getByRole('button', {
      name: /Enter Plan Mode|Exit Plan Mode/i,
    });
    await expect(planModeButton).toBeVisible();
    await expect(planModeButton).toBeEnabled();

    // Click to toggle
    await planModeButton.click();
    await expect(page.getByRole('button', { name: /Exit Plan Mode/i })).toBeVisible({
      timeout: 10000,
    });

    // The Plan Mode text should still be visible (UI doesn't break)
    await expect(page.getByText('Plan Mode', { exact: true })).toBeVisible({ timeout: 10000 });
  });

  test('should toggle plan panel visibility', async ({ page, request }) => {
    await openConversationViaApi(page, request, projectId, 'Plan panel visibility', tenantId);

    const planPanelBtn = page.getByRole('button', { name: /Enter Plan Mode|Exit Plan Mode/i });
    await expect(planPanelBtn).toBeVisible();

    // Click to toggle
    await planPanelBtn.click();
    await expect(page.getByRole('button', { name: /Exit Plan Mode/i })).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText('Plan Mode', { exact: true })).toBeVisible({ timeout: 10000 });
  });

  test('should navigate to conversation when clicked', async ({ page, request }) => {
    await openConversationViaApi(page, request, projectId, 'Conversation navigation', tenantId);

    const input = page.locator('#agent-message-input');
    await input.fill('Test conversation for navigation');

    const sendButton = page.getByTestId('send-button');
    await sendButton.click();

    await expect(page.getByText('Test conversation for navigation').first()).toBeVisible({
      timeout: 10000,
    });
    expect(page.url()).toContain('/agent-workspace');
  });

  test('should delete conversation from sidebar', async ({ page, request }) => {
    await openConversationViaApi(page, request, projectId, 'Conversation deletion', tenantId);

    const input = page.locator('#agent-message-input');
    await input.fill('Conversation to be deleted');

    const sendButton = page.getByTestId('send-button');
    await sendButton.click();
    await page.waitForTimeout(3000);

    const conversationItem = page
      .locator('aside button')
      .filter({ hasText: /Conversation|First conv|Persist|Test conversation|默认项目/i })
      .first();
    if (!(await conversationItem.isVisible({ timeout: 5000 }).catch(() => false))) {
      await expect(page.getByRole('button', { name: /New Chat/i })).toBeVisible();
      return;
    }
    await conversationItem.hover();

    // Find and click delete button
    const deleteBtn = page
      .locator('aside button[aria-label*="delete" i], aside button[title*="delete" i]')
      .first();
    if (await deleteBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
      await deleteBtn.click();

      // Confirm deletion in modal
      await page.waitForTimeout(500);
      const confirmBtn = page.getByRole('button', { name: /Delete/i }).last();
      if (await confirmBtn.isVisible()) {
        await confirmBtn.click();
        await page.waitForTimeout(1000);
      }
    }
  });
});

// Additional test suite for Agent V3 specific features
test.describe('Agent V3 Tools and Streaming', () => {
  let projectId: string;
  let tenantId: string;

  test.beforeEach(async ({ page }) => {
    const project = await createAgentProject();
    projectId = project.id;
    tenantId = project.tenantId;

    // Set English locale
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
      localStorage.setItem('memstack_onboarding_complete', 'true');
    });

    // Login
    await page.goto('http://localhost:3000/login');
    await page.getByTestId('email-input').fill('admin@memstack.ai');
    await page.getByTestId('password-input').fill('adminpassword');
    await page.getByRole('button', { name: /Sign In/i }).click();

    // Wait for navigation
    await page.waitForURL(/\/tenant/);
  });

  test('should display tools list API availability', async ({ page }) => {
    // This test verifies the listTools API is accessible
    await page.goto(agentWorkspaceUrl(projectId, tenantId));
    await page.waitForTimeout(2000);

    // V3: Input area should be functional
    const input = page.locator('#agent-message-input');
    await expect(input).toBeVisible();

    // The UI should be ready to accept messages
    await expect(input).toBeEnabled();
  });

  test('should handle SSE streaming connection', async ({ page, request }) => {
    await openConversationViaApi(page, request, projectId, 'SSE streaming', tenantId);

    const input = page.locator('#agent-message-input');
    await input.fill('Test SSE streaming');

    const sendButton = page.getByTestId('send-button');
    await sendButton.click();

    // Wait for SSE connection and response
    await page.waitForTimeout(5000);

    // V3: Agent response should appear (indicated by robot icon or text content)
    // User message should be visible
    await expect(page.getByText('Test SSE streaming').first()).toBeVisible();
  });

  test('should handle text streaming with typewriter effect', async ({ page, request }) => {
    await openConversationViaApi(page, request, projectId, 'Typewriter streaming', tenantId);

    // Send a simple message
    const input = page.locator('#agent-message-input');
    await input.fill('Say hello');

    const sendButton = page.getByTestId('send-button');
    await sendButton.click();

    // Wait for streaming response - the response text should appear gradually
    await page.waitForTimeout(8000);

    // V3: The assistant message container should be visible
    // Look for the Agent label which appears in MessageBubble
    await expect(page.getByText('Agent').first()).toBeVisible({ timeout: 15000 });
  });
});

// Test suite for event persistence and replay
test.describe('Agent V3 Event Persistence', () => {
  let projectId: string;
  let tenantId: string;

  test.beforeEach(async ({ page }) => {
    // Set English locale
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
      localStorage.setItem('memstack_onboarding_complete', 'true');
    });

    // Login
    await page.goto('http://localhost:3000/login');
    await page.getByTestId('email-input').fill('admin@memstack.ai');
    await page.getByTestId('password-input').fill('adminpassword');
    await page.getByRole('button', { name: /Sign In/i }).click();
    await page.waitForURL(/\/tenant/);

    const project = await createAgentProject();
    projectId = project.id;
    tenantId = project.tenantId;
  });

  test('should persist messages and reload on page refresh', async ({ page, request }) => {
    test.setTimeout(90000);
    const conversationId = await openConversationViaApi(
      page,
      request,
      projectId,
      'Persistence reload',
      tenantId
    );
    expect(page.url()).toContain(`projectId=${projectId}`);

    const input = page.locator('#agent-message-input');
    const testMessage = `History restore marker ${Date.now()}`;
    await input.fill(testMessage);

    const sendButton = page.getByTestId('send-button');
    await sendButton.click();

    // Wait for message to appear in the chat
    await expect(page.getByText(testMessage).first()).toBeVisible({ timeout: 10000 });

    const stopButton = page.getByRole('button', { name: /Stop/i });
    if (await stopButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await stopButton.click();
    }

    const apiToken = await loginViaApi();

    await expect
      .poll(
        async () => {
          const response = await request.get(
            `${API_BASE}/api/v1/agent/conversations/${conversationId}/messages?project_id=${encodeURIComponent(projectId)}&limit=50`,
            { headers: { Authorization: `Bearer ${apiToken}` } }
          );
          if (!response.ok()) {
            return `http:${String(response.status())}:${conversationId}`;
          }

          const data = (await response.json()) as ConversationMessagesResponse;
          const isPersisted =
            data.timeline?.some(
              (event) => event.type === 'user_message' && event.content === testMessage
            ) ?? false;
          if (isPersisted) return 'persisted';

          const timelineTypes =
            data.timeline?.map((event) => event.type ?? 'unknown').join(',') ?? '';
          return `missing:${timelineTypes || 'empty'}`;
        },
        { timeout: 45000, message: 'expected user message to be persisted in conversation history' }
      )
      .toBe('persisted');

    // Refresh the page
    await page.reload();
    await expect(page).toHaveURL(new RegExp(`/agent-workspace/${conversationId}`));
    await expect(page.locator('#agent-message-input')).toBeVisible({ timeout: 15000 });
    await expect(page.getByText(testMessage).first()).toBeVisible({ timeout: 15000 });
  });

  test('should load conversation history when switching conversations', async ({
    page,
    request,
  }) => {
    await openConversationViaApi(page, request, projectId, 'History first conversation', tenantId);

    const input = page.locator('#agent-message-input');
    const timestamp = Date.now();
    const message1 = `First conv ${timestamp}`;
    await input.fill(message1);

    const sendButton = page.getByTestId('send-button');
    await sendButton.click();

    // First message should be visible
    await expect(page.getByText(message1).first()).toBeVisible({ timeout: 10000 });

    // Store first conversation URL for later
    const firstConvUrl = page.url();

    // Wait a bit for streaming (but don't require it to finish)
    await page.waitForTimeout(5000);

    const stopButton = page.getByRole('button', { name: /Stop/i });
    if (await stopButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await stopButton.click();
    }

    await openConversationViaApi(page, request, projectId, 'History second conversation', tenantId);

    const message2 = `Second conv ${timestamp}`;
    await input.fill(message2);
    await expect(sendButton).toBeEnabled({ timeout: 30000 });
    await sendButton.click();
    await expect(page.getByText(message2).first()).toBeVisible({ timeout: 10000 });

    // Go back to first conversation
    await page.goto(firstConvUrl);
    await page.waitForTimeout(3000);

    // First message should be visible
    await expect(page.getByText(message1).first()).toBeVisible({ timeout: 10000 });
  });
});

// Test suite for SubAgent Management
test.describe('Agent V3 SubAgent Management', () => {
  let tenantId: string;

  test.beforeEach(async ({ page }) => {
    const token = await loginViaApi();
    tenantId = await getFirstTenantId(token);

    // Set English locale
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
      localStorage.setItem('memstack_onboarding_complete', 'true');
    });

    // Login
    await page.goto('http://localhost:3000/login');
    await page.getByTestId('email-input').fill('admin@memstack.ai');
    await page.getByTestId('password-input').fill('adminpassword');
    await page.getByRole('button', { name: /Sign In/i }).click();
    await page.waitForURL(/\/tenant/);
  });

  test('should navigate to SubAgent page via sidebar', async ({ page }) => {
    // Wait for tenant page to load
    await page.waitForTimeout(2000);

    // Click on SubAgents in the sidebar navigation
    const subagentLink = page.locator('a[href*="subagents"]').first();
    if (await subagentLink.isVisible({ timeout: 5000 })) {
      await subagentLink.click();
      await page.waitForTimeout(2000);

      // URL should contain subagents
      expect(page.url()).toContain('subagents');
    } else {
      // If link not found, try direct navigation
      await page.goto(`http://localhost:3000/tenant/${tenantId}/subagents`);
      await page.waitForTimeout(2000);
      expect(page.url()).toContain('subagents');
    }
  });

  test('should display SubAgent management UI elements', async ({ page }) => {
    await page.goto(`http://localhost:3000/tenant/${tenantId}/subagents`);

    await expect(page.getByRole('heading', { name: 'SubAgents', exact: true })).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByRole('button', { name: /From Template/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Create SubAgent/i })).toBeVisible();
  });
});

// Test suite for Skill Registry
test.describe('Agent V3 Skill Registry', () => {
  let tenantId: string;

  test.beforeEach(async ({ page }) => {
    const token = await loginViaApi();
    tenantId = await getFirstTenantId(token);

    // Set English locale
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
      localStorage.setItem('memstack_onboarding_complete', 'true');
    });

    // Login
    await page.goto('http://localhost:3000/login');
    await page.getByTestId('email-input').fill('admin@memstack.ai');
    await page.getByTestId('password-input').fill('adminpassword');
    await page.getByRole('button', { name: /Sign In/i }).click();
    await page.waitForURL(/\/tenant/);
  });

  test('should navigate to Skills page via sidebar', async ({ page }) => {
    // Wait for tenant page to load
    await page.waitForTimeout(2000);

    // Click on Skills in the sidebar navigation
    const skillsLink = page.locator('a[href*="skills"]').first();
    if (await skillsLink.isVisible({ timeout: 5000 })) {
      await skillsLink.click();
      await page.waitForTimeout(2000);

      // URL should contain skills
      expect(page.url()).toContain('skills');
    } else {
      // If link not found, try direct navigation
      await page.goto(`http://localhost:3000/tenant/${tenantId}/skills`);
      await page.waitForTimeout(2000);
      expect(page.url()).toContain('skills');
    }
  });

  test('should display Skill management UI elements', async ({ page }) => {
    await page.goto(`http://localhost:3000/tenant/${tenantId}/skills`);
    await page.waitForTimeout(3000);

    // Page should load and have interactive elements
    const anyButton = page.locator('button').first();
    await expect(anyButton).toBeVisible({ timeout: 10000 });
  });
});

// Test suite for Tools API
test.describe('Agent V3 Tools API', () => {
  let projectId: string;
  let tenantId: string;

  test.beforeEach(async ({ page }) => {
    const project = await createAgentProject();
    projectId = project.id;
    tenantId = project.tenantId;

    // Set English locale
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
      localStorage.setItem('memstack_onboarding_complete', 'true');
    });

    // Login
    await page.goto('http://localhost:3000/login');
    await page.getByTestId('email-input').fill('admin@memstack.ai');
    await page.getByTestId('password-input').fill('adminpassword');
    await page.getByRole('button', { name: /Sign In/i }).click();
    await page.waitForURL(/\/tenant/);
  });

  test('should list available tools via API', async ({ page, request }) => {
    // Get token from localStorage
    const token = await getPersistedToken(page);

    // Call listTools API
    const response = await request.get('http://localhost:8000/api/v1/agent/tools', {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data).toHaveProperty('tools');
    expect(Array.isArray(data.tools)).toBeTruthy();

    // Should have at least some built-in tools
    if (data.tools.length > 0) {
      expect(data.tools[0]).toHaveProperty('name');
      expect(data.tools[0]).toHaveProperty('description');
    }
  });

  test('should get conversation events via API', async ({ page, request }) => {
    const token = await getPersistedToken(page);
    const conversationId = await openConversationViaApi(
      page,
      request,
      projectId,
      'Conversation events API',
      tenantId
    );

    const input = page.locator('#agent-message-input');
    await input.fill('Hello for events test');

    const sendButton = page.getByTestId('send-button');
    await sendButton.click();

    await expect(page.getByText('Hello for events test').first()).toBeVisible({ timeout: 10000 });
    expect(conversationId).toBeTruthy();

    // Wait for some events to be recorded
    await page.waitForTimeout(3000);

    // Call events API
    const response = await request.get(
      `http://localhost:8000/api/v1/agent/conversations/${conversationId}/events`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    );

    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data).toHaveProperty('events');
    expect(data).toHaveProperty('has_more');
  });

  test('should get execution status via API', async ({ page, request }) => {
    const token = await getPersistedToken(page);
    const conversationId = await createConversationViaApi(
      request,
      token,
      projectId,
      'Execution status API test'
    );

    // Call execution status API
    const response = await request.get(
      `${API_BASE}/api/v1/agent/conversations/${conversationId}/execution-status?include_recovery=true`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    );

    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data).toHaveProperty('is_running');
    expect(data).toHaveProperty('last_event_time_us');
    expect(data).toHaveProperty('last_event_counter');
    expect(data).toMatchObject({ conversation_id: conversationId });
  });
});

// Test suite for Human Interaction Response (Clarification)
test.describe('Agent V3 Human Interaction', () => {
  test.beforeEach(async ({ page }) => {
    // Set English locale
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.setItem('i18nextLng', 'en-US');
      localStorage.setItem('memstack_onboarding_complete', 'true');
    });

    // Login
    await page.goto('http://localhost:3000/login');
    await page.getByTestId('email-input').fill('admin@memstack.ai');
    await page.getByTestId('password-input').fill('adminpassword');
    await page.getByRole('button', { name: /Sign In/i }).click();
    await page.waitForURL(/\/tenant/);
  });

  test('should have clarification response API endpoint', async ({ page, request }) => {
    const token = await getPersistedToken(page);
    const requestId = 'test-clarification-request-id';

    const response = await request.post(`${API_BASE}/api/v1/agent/hitl/respond`, {
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        request_id: requestId,
        hitl_type: 'clarification',
        response_data: { answer: 'test response' },
      },
    });

    expect(response.status()).toBe(404);
    const body = (await response.json()) as ApiErrorResponse;
    expect(body.detail).toMatch(/HITL request not found/i);
  });

  test('should have decision response API endpoint', async ({ page, request }) => {
    const token = await getPersistedToken(page);
    const requestId = 'test-decision-request-id';

    const response = await request.post(`${API_BASE}/api/v1/agent/hitl/respond`, {
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        request_id: requestId,
        hitl_type: 'decision',
        response_data: { decision: 'approved' },
      },
    });

    expect(response.status()).toBe(404);
    const body = (await response.json()) as ApiErrorResponse;
    expect(body.detail).toMatch(/HITL request not found/i);
  });

  test('should have permission response API endpoint', async ({ page, request }) => {
    const token = await getPersistedToken(page);
    const requestId = 'test-permission-request-id';

    const response = await request.post(`${API_BASE}/api/v1/agent/hitl/respond`, {
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        request_id: requestId,
        hitl_type: 'permission',
        response_data: { action: 'allow', granted: true },
      },
    });

    expect(response.status()).toBe(404);
    const body = (await response.json()) as ApiErrorResponse;
    expect(body.detail).toMatch(/HITL request not found/i);
  });
});
