import { existsSync } from "node:fs";
import { dirname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

test("automation creation uses a fresh conversation and editing preserves a bound session", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem("agistack.desktop.locale", "en"),
  );
  await page.goto("/qa/automations.html");
  await page
    .getByRole("button", { name: "New automation", exact: true })
    .click();
  const editor = page.getByRole("dialog");
  await expect(
    editor.getByRole("combobox", { name: "Conversation", exact: true }),
  ).toHaveText("Start fresh conversation");
  await editor.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await expect(
    editor.getByRole("combobox", { name: "Conversation", exact: true }),
  ).toHaveText("Reuse conversation");
});

test("automation run history opens its matching conversation", async ({
  page,
}) => {
  await page.goto("/qa/automations.html");
  await page
    .getByRole("button", { name: "Open conversation", exact: true })
    .first()
    .click();
  expect(
    await page.evaluate(() => globalThis.__automationOpenedConversation),
  ).toBe("conversation-nightly-review");
});

test("automation reuse requires an explicit conversation and submits its workspace", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem("agistack.desktop.locale", "en"),
  );
  await page.goto("/qa/automations.html");
  await page
    .getByRole("button", { name: "New automation", exact: true })
    .click();
  const editor = page.getByRole("dialog");
  await editor
    .getByRole("combobox", { name: "Conversation", exact: true })
    .click();
  await page
    .getByRole("option", { name: "Reuse conversation", exact: true })
    .click();
  const create = editor.getByRole("button", {
    name: "Create automation",
    exact: true,
  });
  await expect(create).toBeDisabled();
  await editor
    .getByRole("textbox", { name: "Name", exact: true })
    .fill("QA reuse");
  await editor
    .getByRole("textbox", { name: "Instruction or event content", exact: true })
    .fill("Review this conversation");
  await editor
    .getByRole("combobox", { name: "Existing conversation", exact: true })
    .click();
  await page
    .getByRole("option", { name: "Selected review conversation", exact: true })
    .click();
  await expect(create).toBeEnabled();
  await create.click();
  await expect(editor).not.toBeVisible();
  const submitted = await page.evaluate(
    () => globalThis.__automationSubmittedInput,
  );
  expect(submitted.conversation_mode).toBe("reuse");
  expect(submitted.conversation_id).toBe("conversation-selected");
  expect(submitted.workspace_id).toBe("workspace-selected");
});

test("workspace collaboration selects each panel without losing the route", async ({
  page,
}) => {
  await page.goto("/qa/workspace-collaboration.html?state=ready");
  const tabs = page.locator('.workspace-collaboration-tabs > [role="tab"]');
  await expect(tabs).toHaveCount(10);
  for (const tab of await tabs.all()) {
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true");
    await expect(page.locator(".app-fatal-error")).toHaveCount(0);
  }
});

for (const state of ["ready", "stale", "error"]) {
  test(`sandbox switches tool panels while its authority is ${state}`, async ({
    page,
  }) => {
    await page.goto(`/qa/sandbox-runtime.html?state=${state}`);
    const tabs = page.locator(
      '.session-sandbox-tools [role="tablist"] [role="tab"]',
    );
    await expect(tabs).toHaveCount(2);
    for (const tab of await tabs.all()) {
      await tab.click();
      await expect(tab).toHaveAttribute("aria-selected", "true");
    }
  });
}

// This fixture mounts the real preview surface against controlled local artifacts.
test("artifact preview changes format without an error state", async ({
  page,
}) => {
  const REPOSITORY_ROOT = resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../../../..",
  );
  const STATIC_ASSET_ROOTS = ["artifacts", "design-prototype", "docs"].map(
    (directory) => resolve(REPOSITORY_ROOT, directory),
  );
  await page.route(
    /\/(?:artifacts|design-prototype|docs)\//u,
    async (route) => {
      const pathname = decodeURIComponent(
        new URL(route.request().url()).pathname,
      );
      const candidate = resolve(REPOSITORY_ROOT, `.${pathname}`);
      const allowed = STATIC_ASSET_ROOTS.some(
        (root) => candidate === root || candidate.startsWith(`${root}${sep}`),
      );
      if (!allowed || !existsSync(candidate)) {
        await route.abort("blockedbyclient");
        return;
      }
      await route.fulfill({ path: candidate });
    },
  );
  await page.goto("/qa/artifact-preview.html");
  const formatButtons = page.locator(
    ".parity-runtime-qa__preview-nav button[data-qa-format]",
  );
  await expect(formatButtons).toHaveCount(9);
  for (let index = 0; index < 9; index += 1) {
    const button = formatButtons.nth(index);
    const format = await button.getAttribute("data-qa-format");
    expect(format).toBeTruthy();
    await button.click();
    await expect(
      page.locator(`header[data-qa-format="${format}"]`),
    ).toBeVisible();
    await expect(
      page.locator('.artifact-preview-state[role="status"]'),
    ).toHaveCount(0);
    await expect(
      page.locator('.artifact-preview-state[role="alert"]'),
    ).toHaveCount(0);
  }
});
