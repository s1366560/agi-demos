import path from 'node:path';

import { createTestProject, getAdminAuthToken, loginAsAdmin, test, expect } from './base';

test('imports two signed versions, executes each, rolls back and uninstalls', async ({ page }) => {
  test.setTimeout(180_000);
  const packages = process.env.E2E_NOTES_PACKAGES;
  if (!packages) throw new Error('Set E2E_NOTES_PACKAGES to the trusted signed Notes archives');
  const project = await createTestProject({
    name: `Optional business ${Date.now()}`,
    description: 'Signed package lifecycle',
    token: await getAdminAuthToken(),
  });

  await loginAsAdmin(page);
  await page.goto(`/tenant/${project.tenantId}/plugins?projectId=${project.id}`);
  const market = page.getByTestId('plugin-market');
  const dialog = page.getByRole('dialog');
  const frame = market.getByTestId('signed-business-slot');
  const guest = frame.contentFrame();

  async function openAction(name: string) {
    const action = market.getByRole('button', { name, exact: true });
    if (!(await action.isVisible()))
      await market.getByText('More actions', { exact: true }).click();
    await action.click();
  }

  async function importFile(version: string) {
    const chooser = page.waitForEvent('filechooser');
    await openAction('Import signed file');
    await (await chooser).setFiles(path.join(packages!, `notes-${version}.mspkg`));
    await expect(dialog).toContainText('sample.notes');
    await expect(dialog).toContainText(version);
    await expect(dialog).toContainText('tools.execute');
    await dialog.getByRole('button', { name: 'Approve and enable' }).click();
    await expect(dialog).toBeHidden();
  }

  async function verifyRelease(title: string, result: string) {
    await expect(guest.getByRole('heading', { name: title, exact: true })).toBeVisible();
    await guest.getByRole('button', { name: 'Save note' }).click();
    await expect(market.locator('pre[aria-live]')).toContainText(`"op": "${result}"`);
  }

  await expect(frame).toHaveCount(0);
  await importFile('1.0.0');
  await verifyRelease('Notes', 'ping');
  await importFile('1.1.0');
  await verifyRelease('Notes updated', 'pong');
  await openAction('Roll back to 1.0.0');
  await dialog.getByRole('button', { name: 'Confirm', exact: true }).click();
  await verifyRelease('Notes', 'ping');
  await openAction('Uninstall');
  await dialog.getByRole('button', { name: 'Uninstall', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(frame).toHaveCount(0);
  await market.getByRole('button', { name: 'Back to marketplace' }).click();
  await market.getByRole('button', { name: 'Installed', exact: true }).click();
  await expect(market.getByText('No plugins installed in this project')).toBeVisible();
});
