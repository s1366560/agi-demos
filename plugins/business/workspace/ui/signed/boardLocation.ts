import type { RichPageContext } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';

const sections = {
  posts: 'discussion',
  tasks: 'goals',
  members: 'members',
  settings: 'settings',
} as const;

export function boardLocation(context: RichPageContext) {
  const params=new URLSearchParams(context.search);
  const match=/\/workspaces\/([^/]+)(?:\/(members|posts|tasks|settings))?\/?$/.exec(context.pathname);
  const id=match?decodeURIComponent(match[1]):params.get('workspaceId');
  const section=match?.[2] as keyof typeof sections | undefined;
  if(id)params.set('workspaceId',id);
  const tab=section?sections[section]:undefined;
  if(tab) params.set('tab',tab);
  return {id,tab,params};
}
