import { User } from 'lucide-react';

export function UserAvatar() {
  return (
    <div className="w-8 h-8 rounded-lg bg-slate-100/80 dark:bg-slate-800/70 ring-1 ring-slate-200/45 dark:ring-slate-700/45 flex items-center justify-center flex-shrink-0">
      <User size={16} className="text-slate-500 dark:text-slate-400" />
    </div>
  );
}

export function UserBubble({ content, isForced = false }: { content: string; isForced?: boolean }) {
  return (
    <div
      className={
        isForced
          ? 'bg-slate-50/80 dark:bg-slate-800/70 rounded-lg rounded-br-sm px-4 py-2'
          : 'bg-slate-50/80 dark:bg-slate-800/70 border border-slate-200/40 dark:border-slate-700/40 rounded-lg rounded-br-sm px-4 py-2 shadow-[0_1px_2px_rgba(15,23,42,0.02)]'
      }
    >
      <p className="text-sm leading-[1.5] whitespace-pre-wrap break-words text-slate-800 dark:text-slate-100 font-normal">
        {content}
      </p>
    </div>
  );
}
