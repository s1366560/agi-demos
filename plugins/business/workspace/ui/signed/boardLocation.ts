import type { RichPageContext } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import type { WorkspaceCollaborationSurface } from '../desktop/workspace/workspaceCollaborationClient';

const sections = {
  posts: 'discussion',
  tasks: 'goals',
  members: 'members',
  settings: 'settings',
  files: 'files',
} as const;
const surfaces: readonly WorkspaceCollaborationSurface[] = [
  ...Object.values(sections),
  'status',
  'collaboration',
  'notes',
  'genes',
  'topology',
];

function surface(value: string | null) {
  return surfaces.find((item) => item === value);
}

export function boardLocation(context: RichPageContext) {
  const params = new URLSearchParams(context.search);
  const match =
    /\/workspaces\/([^/]+)(?:\/(members|posts|tasks|settings|files)(?:\/([^/]+))?)?\/?$/.exec(
      context.pathname
    );
  const id = match ? decodeURIComponent(match[1]!) : params.get('workspaceId');
  const section = match?.[2] as keyof typeof sections | undefined;
  if (id) params.set('workspaceId', id);
  const tab = section ? sections[section] : surface(params.get('tab'));
  if (tab) params.set('tab', tab);
  if (section === 'tasks' && match?.[3]) params.set('taskId', decodeURIComponent(match[3]));
  return { id, tab, params };
}

/** Project the board's internal route back into the workspace bookmark family it was opened from. */
export function boardAddress(context: RichPageContext, search: URLSearchParams, hash: string) {
  const params = new URLSearchParams(search);
  let pathname = context.pathname;
  const workspace = params.get('workspaceId');
  const parts = /^(.*\/workspaces)\/[^/]+(?:\/.*)?$/.exec(pathname);
  if (parts && workspace) {
    pathname = parts[1] + '/' + encodeURIComponent(workspace);
    params.delete('workspaceId');
    const tab = params.get('tab') || 'goals';
    const section = Object.entries(sections).find(([, value]) => value === tab)?.[0];
    const task = tab === 'goals' ? params.get('taskId') : null;
    if (section && (tab !== 'goals' || task || /\/tasks(?:\/|$)/.test(context.pathname))) {
      pathname += '/' + section;
      params.delete('tab');
      if (task) {
        pathname += '/' + encodeURIComponent(task);
        params.delete('taskId');
      }
    }
  }
  const query = params.toString();
  return pathname + (query ? '?' + query : '') + hash;
}
