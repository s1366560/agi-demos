import { expect, test } from '@playwright/test';

test('signed package install, enable, rollback, and uninstall are visible', async ({ page }) => {
  await page.goto('/e2e/fixtures/optional-business-lifecycle.html');
  await page.getByRole('button', { name: 'Install', exact: true }).click();
  await expect(page.getByTestId('signed-business-slot')).toHaveCount(0);
  await page.getByRole('button', { name: 'Enable', exact: true }).click();
  const frame = page.getByTestId('signed-business-slot');
  await expect(frame).toBeVisible();
  await expect(frame).toHaveAttribute('srcdoc', /Notes/);
  await page.getByRole('button', { name: 'Enable' }).click();
  await expect(frame).toHaveAttribute('srcdoc', /Notes updated/);
  await page.getByRole('button', { name: 'Rollback' }).click();
  await expect(frame).toHaveAttribute('srcdoc', /<h1>Notes<\/h1>/);
  await page.getByRole('button', { name: 'Uninstall' }).click();
  await expect(page.getByTestId('signed-business-slot')).toHaveCount(0);
});
