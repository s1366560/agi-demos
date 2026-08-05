import type { ProjectWorkItem } from '../../types';
import {
  myWorkEffectiveGroup,
  myWorkItemKey,
  myWorkItemSummary,
} from '../my-work/myWorkModel';

// Activity 收件箱的三个聚合分类,展示顺序固定。
export type ActivityCategory = 'needs_input' | 'ready_for_review' | 'attention';

export const ACTIVITY_CATEGORIES: readonly ActivityCategory[] = Object.freeze([
  'needs_input',
  'ready_for_review',
  'attention',
]);

// 运行进入这些终态/异常态时视为「需要关注」,不再归入「待回顾」。
const ATTENTION_RUN_STATUSES: ReadonlySet<string> = new Set([
  'failed',
  'cancelled',
  'interrupted',
  'disconnected',
]);

export type ActivityInboxEntry = {
  // 与 My Work 一致的权威标识(authority_kind:authority_id),也是已读位的键。
  id: string;
  // 原始权威记录,用于跳转回所属会话。
  item: ProjectWorkItem;
  conversationId: string;
  title: string;
  category: ActivityCategory;
  // ISO 时间戳与其毫秒值;排序与未读判断均以毫秒值为准。
  timestamp: string;
  timestampMs: number;
  // 后端摘要;为空时视图回退到动作文案(actionKey)。
  subtitle: string | null;
  actionKey: string;
  statusKey: string;
};

export type ActivityInboxGroup = Readonly<{
  category: ActivityCategory;
  entries: ActivityInboxEntry[];
}>;

export function activityCategoryForItem(
  item: Pick<ProjectWorkItem, 'group' | 'status' | 'required_action'>,
): ActivityCategory | null {
  if (
    item.required_action === 'inspect_failure' ||
    ATTENTION_RUN_STATUSES.has(item.status)
  ) {
    return 'attention';
  }
  // 以后端分组为基准,但以运行真实状态校正:终态会话不得呈现为待输入/进行中。
  const group = myWorkEffectiveGroup(item);
  if (group === 'needs_input' || group === 'needs_approval') {
    return 'needs_input';
  }
  if (group === 'ready_review') {
    return 'ready_for_review';
  }
  // 仍在运行的条目不进收件箱,避免与 My Work 的 Running 分组重复。
  return null;
}

export function activityEntryForItem(
  item: ProjectWorkItem,
): ActivityInboxEntry | null {
  const category = activityCategoryForItem(item);
  if (!category) return null;
  const timestamp = item.updated_at || item.created_at;
  const parsed = Date.parse(timestamp);
  return {
    id: myWorkItemKey(item),
    item,
    conversationId: item.conversation_id,
    title: item.title,
    category,
    timestamp,
    timestampMs: Number.isFinite(parsed) ? parsed : 0,
    subtitle: myWorkItemSummary(item),
    actionKey: `myWork.action.${item.required_action}`,
    statusKey: `myWork.status.${item.status}`,
  };
}

export function buildActivityInboxEntries(
  items: ProjectWorkItem[],
): ActivityInboxEntry[] {
  return items
    .map(activityEntryForItem)
    .filter((entry): entry is ActivityInboxEntry => entry !== null)
    .sort((left, right) => right.timestampMs - left.timestampMs);
}

export function groupActivityEntries(
  entries: ActivityInboxEntry[],
): ActivityInboxGroup[] {
  return ACTIVITY_CATEGORIES.map((category) => ({
    category,
    entries: entries.filter((entry) => entry.category === category),
  }));
}
