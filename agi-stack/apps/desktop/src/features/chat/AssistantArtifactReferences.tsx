import { DownloadIcon, FileIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import {
  assistantArtifactReferences,
  formatAssistantArtifactSize,
} from './assistantArtifactReferenceModel';

export function AssistantArtifactReferences({
  artifacts,
  metadata,
}: {
  artifacts?: unknown;
  metadata?: unknown;
}) {
  const { t } = useI18n();
  const references = assistantArtifactReferences({ artifacts, metadata });
  if (references.length === 0) return null;

  return (
    <ul className="assistant-artifact-references" aria-label={t('chat.artifacts')}>
      {references.map((reference) => (
        <li key={reference.key}>
          <a
            className="assistant-artifact-reference"
            href={reference.url}
            target="_blank"
            rel="noopener noreferrer"
            download
            aria-label={reference.label}
          >
            <span className="assistant-artifact-reference-icon" aria-hidden="true">
              <FileIcon />
            </span>
            <span className="assistant-artifact-reference-name" title={reference.label}>
              {reference.label}
            </span>
            {reference.sizeBytes !== null ? (
              <span className="assistant-artifact-reference-size">
                {formatAssistantArtifactSize(reference.sizeBytes)}
              </span>
            ) : null}
            <DownloadIcon className="assistant-artifact-reference-download" aria-hidden="true" />
          </a>
        </li>
      ))}
    </ul>
  );
}
