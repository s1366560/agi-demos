import { useTranslation } from 'react-i18next';

import { EmptyState } from '../EmptyState';
import { HostedProjectionBadge } from '../HostedProjectionBadge';

import type { BlackboardNoteCard } from '../blackboardUtils';

export interface NotesTabProps {
  notes: BlackboardNoteCard[];
}

export function NotesTab({ notes }: NotesTabProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-4">
      <HostedProjectionBadge
        labelKey="blackboard.notesSurfaceHint"
        fallbackLabel="workspace note projection"
      />

      {notes.map((note) => (
        <article
          key={note.id}
          className="rounded-xl border border-border-light bg-surface-muted p-5 dark:border-border-dark dark:bg-surface-dark-alt"
        >
          <div className="flex flex-wrap items-center gap-3">
            <span className="rounded-full border border-border-light bg-surface-light px-3 py-1 text-[11px] uppercase tracking-widest text-text-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
              {t(`blackboard.noteKinds.${note.kind}`, note.kind)}
            </span>
          </div>
          <h3 className="mt-4 break-words text-lg font-semibold text-text-primary dark:text-text-inverse">
            {note.title}
          </h3>
          <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-7 text-text-secondary dark:text-text-muted">
            {note.summary}
          </p>
        </article>
      ))}

      {notes.length === 0 && (
        <EmptyState>
          {t(
            'blackboard.noNotes',
            'No shared notes yet. Add workspace description, objectives, or pinned discussions to make this tab more useful.'
          )}
        </EmptyState>
      )}
    </div>
  );
}
