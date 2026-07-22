import { Badge } from '@radix-ui/themes';
import { FileTextIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { LiveArtifactCanvasState } from './artifactCanvasEventModel';
import './LiveArtifactCanvas.css';

type LiveArtifactCanvasProps = {
  state: LiveArtifactCanvasState;
  onSelect: (artifactId: string) => void;
};

export function LiveArtifactCanvas({ state, onSelect }: LiveArtifactCanvasProps) {
  const { t } = useI18n();
  const active =
    state.tabs.find((candidate) => candidate.id === state.activeArtifactId) ??
    state.tabs[state.tabs.length - 1];
  if (!active) return null;
  const title = active.title || t('artifact.untitled');
  const language = active.language || active.contentType;

  return (
    <section className="live-artifact-canvas" aria-label={t('artifact.liveCanvas')}>
      <header>
        <span>
          <FileTextIcon aria-hidden="true" />
          <span>
            <strong>{title}</strong>
            <small>{t('artifact.liveCanvasDescription')}</small>
          </span>
        </span>
        <Badge color="cyan" variant="soft">
          {language}
        </Badge>
      </header>
      <nav role="tablist" aria-label={t('artifact.liveArtifactTabs')}>
        {state.tabs.map((tab) => (
          <button
            type="button"
            role="tab"
            aria-selected={tab.id === active.id}
            className={tab.id === active.id ? 'selected' : ''}
            key={tab.id}
            onClick={() => onSelect(tab.id)}
          >
            {tab.title || t('artifact.untitled')}
          </button>
        ))}
      </nav>
      <article aria-label={t('artifact.liveArtifactContent', { title })}>
        <pre>
          <code>{active.content}</code>
        </pre>
      </article>
    </section>
  );
}
