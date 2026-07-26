import { useEffect, useState } from 'react';
import {
  ArchiveIcon,
  CheckCircledIcon,
  CodeIcon,
  CrossCircledIcon,
  DownloadIcon,
  FileIcon,
  FileTextIcon,
  ImageIcon,
  SpeakerLoudIcon,
  UpdateIcon,
  VideoIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { AgentTimelineItem } from '../../types';
import {
  artifactTimelineCard,
  formatArtifactTimelineSize,
  type ArtifactTimelineIconKind,
} from './artifactTimelineCardModel';

function ArtifactIcon({ kind }: { kind: ArtifactTimelineIconKind }) {
  if (kind === 'image') return <ImageIcon />;
  if (kind === 'video') return <VideoIcon />;
  if (kind === 'audio') return <SpeakerLoudIcon />;
  if (kind === 'document') return <FileTextIcon />;
  if (kind === 'code') return <CodeIcon />;
  if (kind === 'archive') return <ArchiveIcon />;
  return <FileIcon />;
}

export function ArtifactTimelineCard({ item }: { item: AgentTimelineItem }) {
  const { t } = useI18n();
  const card = artifactTimelineCard(item);
  const [previewFailed, setPreviewFailed] = useState(false);

  useEffect(() => {
    setPreviewFailed(false);
  }, [card.previewUrl]);

  return (
    <article
      className={`artifact-timeline-card status-${card.status}`}
      data-timeline-anchor-id={item.id}
      tabIndex={-1}
      aria-label={t('chat.artifactCardLabel', { filename: card.filename })}
    >
      <header>
        <span className="artifact-timeline-icon" aria-hidden="true">
          <ArtifactIcon kind={card.iconKind} />
        </span>
        <span className="artifact-timeline-heading">
          <strong>{t('chat.artifactFileGenerated')}</strong>
          {card.sourceTool ? <small>{card.sourceTool}</small> : null}
        </span>
        <span className={`artifact-timeline-status ${card.status}`}>
          {card.status === 'uploading' ? (
            <UpdateIcon className="artifact-timeline-spin" aria-hidden="true" />
          ) : card.status === 'ready' ? (
            <CheckCircledIcon aria-hidden="true" />
          ) : (
            <CrossCircledIcon aria-hidden="true" />
          )}
          {t(`chat.artifactStatus.${card.status}`)}
        </span>
      </header>

      {card.previewUrl && !previewFailed ? (
        <div className="artifact-timeline-image">
          <img
            src={card.previewUrl}
            alt={card.filename}
            loading="lazy"
            onError={() => setPreviewFailed(true)}
          />
        </div>
      ) : null}
      {card.previewUrl && previewFailed ? (
        <div className="artifact-timeline-preview-failed" role="status">
          <CrossCircledIcon aria-hidden="true" />
          <span>{t('chat.artifactImageLoadFailed')}</span>
        </div>
      ) : null}

      <div className="artifact-timeline-file">
        <span>
          <FileIcon aria-hidden="true" />
          <strong title={card.filename}>{card.filename}</strong>
        </span>
        {card.sizeBytes !== null ? (
          <small>{formatArtifactTimelineSize(card.sizeBytes)}</small>
        ) : null}
        {card.downloadUrl ? (
          <a
            href={card.downloadUrl}
            target="_blank"
            rel="noopener noreferrer"
            download={card.filename}
            aria-label={t('chat.artifactDownloadLabel', { filename: card.filename })}
          >
            <DownloadIcon aria-hidden="true" />
            {t('chat.artifactDownload')}
          </a>
        ) : null}
      </div>

      {card.error ? <p className="artifact-timeline-error">{card.error}</p> : null}
      {card.mimeType || card.category ? (
        <footer>
          {card.mimeType ? <span>{card.mimeType}</span> : null}
          {card.category ? <span>{card.category}</span> : null}
        </footer>
      ) : null}
    </article>
  );
}
