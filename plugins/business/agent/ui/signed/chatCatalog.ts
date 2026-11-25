import type { CommandInfo, SkillResponse } from '../../../../../web/src/types/agent';
import { invoke } from './reviewAuthority';

// Each isolated page has one scope and one signed release. Both halves of the
// original slash picker read the same scoped command response.
type Catalog = { commands: CommandInfo[]; skills: SkillResponse[] };
export function readChatCatalog(signal?: AbortSignal) {
  return invoke<Catalog>('chat-project-context', { view: 'commands' }, signal ? { signal } : {});
}

let opening: Promise<Catalog> | undefined;
function pickerCatalog() {
  opening ??= readChatCatalog().finally(() => { opening = undefined; });
  return opening;
}
export const commandAPI = { list: async () => ({ commands: (await pickerCatalog()).commands }) };
export const skillAPI = { list: async () => ({ skills: (await pickerCatalog()).skills }) };
