import { createRoot } from 'react-dom/client';
import { CloudBusinessPage } from '../src/features/settings/CloudBusinessPage';
import { createMarketplaceClient } from '../../../packages/plugin-marketplace-ui/src/client';

// The image lifecycle test supplies a disposable user session and real project scope.
export async function mountWorkspace(
  accessToken: string,
  scope: { tenant_id: string; project_id: string }
) {
  const client = createMarketplaceClient(async (path, options) => {
    const response = await fetch(path, {
      method: options.method,
      signal: options.signal,
      headers: {
        Authorization: 'Bearer ' + accessToken,
        'Content-Type': 'application/json',
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    return response.json();
  }, scope);
  const list = await client.installations();
  const item = list.items.find((entry) => entry.plugin_id === 'memstack-workspace');
  if (!item?.actual_digest || !item.has_desktop_ui) throw new Error('Workspace is unavailable');
  createRoot(document.getElementById('root')!).render(
    <CloudBusinessPage
      client={client}
      item={item}
      digest={item.actual_digest}
      label="Open workspace"
    />
  );
}
