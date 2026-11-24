import type { RichPageRuntime } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import type { Workspace } from '../web/types/workspace';

export async function readDirectory(host: RichPageRuntime, signal?: AbortSignal) {
  const rows: Workspace[] = [];
  const limit = 100;
  while (true) {
    const page = (await host.invoke(
      'list-directory',
      { cards: true, offset: rows.length, limit },
      { signal }
    )) as { rows: Workspace[] };
    rows.push(...page.rows);
    if (page.rows.length < limit) return rows;
  }
}
