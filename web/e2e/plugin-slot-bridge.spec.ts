import { expect, test } from '@playwright/test';

test('packaged opaque iframe exchanges owner context/actions on a private port and retires cleanly', async ({
  page,
}) => {
  const errors: string[] = [];
  const requests: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    if (request.url().includes('platform-plugin-modules')) requests.push(request.url());
  });
  await page.goto('/e2e/fixtures/plugin-slot-bridge.html');
  const frame = page.getByTestId('plugin-slot-settings');
  await expect(frame).toHaveAttribute('data-ready', 'true');
  await expect(frame).toHaveAttribute('sandbox', 'allow-scripts');
  expect(
    await frame.evaluate((element: HTMLIFrameElement) => {
      try {
        return element.contentWindow?.document.body.innerHTML;
      } catch {
        return 'opaque';
      }
    })
  ).toBe('opaque');
  const guest = frame.contentFrame();
  await guest.getByRole('button', { name: 'Open graph' }).click();
  await expect(page.getByTestId('action')).toHaveText('1:graph');
  const oldDocument = await frame.getAttribute('srcdoc');
  await page.getByRole('button', { name: 'Update context' }).click();
  await expect(guest.getByRole('button', { name: 'Graph updated' })).toBeVisible();
  expect(await frame.getAttribute('srcdoc')).toBe(oldDocument);
  await page.getByRole('button', { name: 'Replace generation' }).click();
  await expect(frame).toHaveAttribute('data-ready', 'true');
  expect(await frame.getAttribute('srcdoc')).not.toBe(oldDocument);
  await frame.contentFrame().getByRole('button', { name: 'Graph updated' }).click();
  await expect(page.getByTestId('action')).toHaveText('2:graph');
  await page.getByRole('button', { name: 'Disable slot' }).click();
  await expect(frame).toHaveCount(0);
  await page.evaluate(() =>
    window.postMessage(
      {
        source: 'memstack-plugin-slot-v2',
        type: 'slot:action',
        slotId: 'settings',
        instanceNonce: 'stale',
        generationId: 'generation-1',
        action: { type: 'settings.open', sectionId: 'graph' },
      },
      '*'
    )
  );
  await expect(page.getByTestId('action')).toHaveText('2:graph');
  expect(requests).toEqual([]);
  expect(errors).toEqual([]);
});
