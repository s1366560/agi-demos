import type {
  ActivityReadReceipt,
  ProjectWorkItem,
} from '@/services/projectWorkService';

const itemRevision = (item: ProjectWorkItem): number =>
  typeof item.revision === 'number' ? item.revision : 0;

export function activityEntryIsRead(
  item: ProjectWorkItem,
  receipt: ActivityReadReceipt | undefined
): boolean {
  return receipt !== undefined && receipt.entry_revision >= itemRevision(item);
}

export function buildReadReceipt(
  item: ProjectWorkItem,
  readAt: string
): ActivityReadReceipt {
  return {
    entry_id: item.id,
    entry_revision: itemRevision(item),
    read_at: readAt,
  };
}

export function countUnreadProjectWork(
  items: ProjectWorkItem[],
  receipts: ActivityReadReceipt[]
): number {
  const receiptById = new Map(receipts.map((receipt) => [receipt.entry_id, receipt]));
  return items.reduce(
    (count, item) =>
      count + (activityEntryIsRead(item, receiptById.get(item.id)) ? 0 : 1),
    0
  );
}

export function reconcilePendingActivityReceipts(
  items: ProjectWorkItem[],
  pending: ActivityReadReceipt[]
): ActivityReadReceipt[] {
  const itemById = new Map(items.map((item) => [item.id, item]));
  const reconciled = new Map<string, ActivityReadReceipt>();
  for (const receipt of pending) {
    const item = itemById.get(receipt.entry_id);
    if (!item) continue;
    const candidate = buildReadReceipt(item, receipt.read_at);
    const existing = reconciled.get(receipt.entry_id);
    if (!existing || candidate.read_at > existing.read_at) {
      reconciled.set(receipt.entry_id, candidate);
    }
  }
  return [...reconciled.values()];
}
