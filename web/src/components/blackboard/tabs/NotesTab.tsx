import { useTranslation } from 'react-i18next';

import type { BlackboardNoteCard } from '../blackboardUtils';

export interface NotesTabProps {
  notes: BlackboardNoteCard[];
}

export function NotesTab({ notes }: NotesTabProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-4">
      {notes.map((note) => (
        <article
          key={note.id}
          className="rounded-xl border border-border-light bg-surface-muted p-5 dark:border-border-dark dark:bg-surface-dark-alt"
        >
          <div className="flex flex-wrap items-center gap-3">
            <span className="rounded-full border border-border-light bg-surface-light px-3 py-1 text-[11px] uppercase tracking-[0.16em] text-text-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
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
        <div className="rounded-xl border border-dashed border-border-separator bg-surface-light p-8 text-center text-sm text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
          {t(
            'blackboard.noNotes',
            'No shared notes yet. Add workspace description, objectives, or pinned discussions to make this tab more useful.'
          )}
        </div>
      )}
    </div>
  );
}
