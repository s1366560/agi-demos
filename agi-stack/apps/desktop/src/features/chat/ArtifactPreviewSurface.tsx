import { useEffect, useRef, useState } from 'react';

import { useI18n } from '../../i18n';
import type { DesktopArtifactClient } from './desktopArtifactClient';
import { planArtifactPreview, type ArtifactPreviewPlan } from './artifactPreviewModel';

type ArtifactPreviewSurfaceProps = {
  artifactId: string;
  client: DesktopArtifactClient;
  mimeType?: string;
  sizeBytes?: number;
  title: string;
};

type ReadyPreview = {
  phase: 'ready';
  plan: Extract<ArtifactPreviewPlan, { kind: 'preview' }>;
  blob: Blob;
  bytes: ArrayBuffer | null;
  objectUrl: string | null;
};

type PreviewState =
  | { phase: 'loading' }
  | { phase: 'error'; reasonCode: string }
  | {
      phase: 'download';
      reasonCode: string;
      blob: Blob;
    }
  | ReadyPreview;

type WorkbookSheet = {
  name: string;
  rows: (string | number | boolean | null)[][];
};

const MAX_WORKBOOK_SHEETS = 50;
const MAX_WORKBOOK_ROWS = 2_000;
const MAX_WORKBOOK_COLUMNS = 100;

export function ArtifactPreviewSurface({
  artifactId,
  client,
  mimeType,
  sizeBytes,
  title,
}: ArtifactPreviewSurfaceProps) {
  const { t } = useI18n();
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<PreviewState>({ phase: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setState({ phase: 'loading' });
    void client
      .download(artifactId, controller.signal)
      .then(async (blob) => {
        if (controller.signal.aborted) return;
        const blobMime =
          blob.type && blob.type.toLowerCase() !== 'application/octet-stream'
            ? blob.type
            : undefined;
        const resolvedMime = normalizePreviewMime(blobMime || mimeType, title);
        const plan = planArtifactPreview({
          artifactId,
          mimeType: resolvedMime,
          sizeBytes: blob.size || sizeBytes || 0,
          integrity: 'ready',
        });
        if (plan.kind === 'download') {
          setState({ phase: 'download', reasonCode: plan.reason, blob });
          return;
        }

        let previewBlob = blob;
        let bytes: ArrayBuffer | null = null;
        if (plan.transform === 'sanitize_svg') {
          const sanitized = sanitizeArtifactSvg(await blob.text());
          if (!sanitized) {
            setState({ phase: 'download', reasonCode: 'corrupt_content', blob });
            return;
          }
          previewBlob = new Blob([sanitized], { type: 'image/svg+xml' });
        } else if (plan.renderer === 'html_iframe') {
          previewBlob = new Blob([sanitizeArtifactHtml(await blob.text())], {
            type: 'text/html',
          });
        } else if (plan.renderer === 'docx' || plan.renderer === 'xlsx') {
          bytes = await blob.arrayBuffer();
        }

        if (controller.signal.aborted) return;
        if (plan.objectUrl === 'required') {
          objectUrl = URL.createObjectURL(previewBlob);
        }
        setState({
          phase: 'ready',
          plan,
          blob,
          bytes,
          objectUrl,
        });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || isAbortError(error)) return;
        setState({ phase: 'error', reasonCode: 'artifact_preview_load_failed' });
      });

    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [artifactId, attempt, client, mimeType, sizeBytes, title]);

  if (state.phase === 'loading') {
    return (
      <div className="artifact-preview-state" role="status">
        {t('artifact.previewLoading')}
      </div>
    );
  }
  if (state.phase === 'error') {
    return (
      <div className="artifact-preview-state" role="alert" data-reason-code={state.reasonCode}>
        <span>{t('artifact.previewFailed')}</span>
        <button type="button" onClick={() => setAttempt((current) => current + 1)}>
          {t('common.retry')}
        </button>
      </div>
    );
  }
  if (state.phase === 'download') {
    return (
      <ArtifactDownloadFallback
        blob={state.blob}
        filename={title}
        reasonCode={state.reasonCode}
      />
    );
  }

  return <ReadyArtifactPreview state={state} title={title} />;
}

function ReadyArtifactPreview({ state, title }: { state: ReadyPreview; title: string }) {
  const { t } = useI18n();
  const { renderer } = state.plan;
  if (renderer === 'html_iframe' || renderer === 'sanitized_svg') {
    return (
      <iframe
        className="artifact-preview-frame"
        sandbox=""
        referrerPolicy="no-referrer"
        src={state.objectUrl ?? undefined}
        title={t('artifact.previewTitle', { title })}
      />
    );
  }
  if (renderer === 'pdf_iframe') {
    return (
      <iframe
        className="artifact-preview-frame"
        referrerPolicy="no-referrer"
        src={state.objectUrl ?? undefined}
        title={t('artifact.previewTitle', { title })}
      />
    );
  }
  if (renderer === 'image') {
    return (
      <img
        className="artifact-preview-image"
        src={state.objectUrl ?? undefined}
        alt={title}
      />
    );
  }
  if (renderer === 'audio') {
    return (
      <audio
        className="artifact-preview-media"
        src={state.objectUrl ?? undefined}
        controls
        preload="metadata"
      />
    );
  }
  if (renderer === 'video') {
    return (
      <video
        className="artifact-preview-media"
        src={state.objectUrl ?? undefined}
        controls
        preload="metadata"
      />
    );
  }
  if (renderer === 'docx' && state.bytes) {
    return (
      <DocxArtifactPreview
        bytes={state.bytes}
        blob={state.blob}
        filename={title}
      />
    );
  }
  if (renderer === 'xlsx' && state.bytes) {
    return (
      <XlsxArtifactPreview
        bytes={state.bytes}
        blob={state.blob}
        filename={title}
      />
    );
  }
  return (
    <ArtifactDownloadFallback
      blob={state.blob}
      filename={title}
      reasonCode="unsupported_mime"
    />
  );
}

function DocxArtifactPreview({
  bytes,
  blob,
  filename,
}: {
  bytes: ArrayBuffer;
  blob: Blob;
  filename: string;
}) {
  const { t } = useI18n();
  const containerRef = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    const container = containerRef.current;
    if (!container) return undefined;
    container.replaceChildren();
    void import('docx-preview')
      .then(async ({ renderAsync }) => {
        if (cancelled || !containerRef.current) return;
        await renderAsync(bytes.slice(0), containerRef.current, undefined, {
          className: 'artifact-docx-preview',
          inWrapper: true,
          ignoreWidth: false,
          ignoreHeight: true,
          breakPages: true,
          renderHeaders: true,
          renderFooters: true,
          renderFootnotes: true,
          renderEndnotes: true,
        });
        if (!cancelled && containerRef.current) {
          sanitizeRenderedDocument(containerRef.current);
        }
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      container.replaceChildren();
    };
  }, [bytes]);

  if (failed) {
    return (
      <ArtifactDownloadFallback
        blob={blob}
        filename={filename}
        reasonCode="office_preview_unavailable"
      />
    );
  }
  return (
    <div
      ref={containerRef}
      className="artifact-preview-docx"
      aria-label={t('artifact.docxPreview')}
    />
  );
}

function XlsxArtifactPreview({
  bytes,
  blob,
  filename,
}: {
  bytes: ArrayBuffer;
  blob: Blob;
  filename: string;
}) {
  const { t } = useI18n();
  const [sheets, setSheets] = useState<WorkbookSheet[]>([]);
  const [activeSheet, setActiveSheet] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    setSheets([]);
    setActiveSheet(0);
    void import('xlsx')
      .then((XLSX) => {
        const workbook = XLSX.read(bytes.slice(0), {
          type: 'array',
          cellHTML: false,
          cellText: true,
        });
        const nextSheets = workbook.SheetNames.slice(0, MAX_WORKBOOK_SHEETS).map(
          (name) => {
            const sheet = workbook.Sheets[name];
            const rawRows = sheet
              ? (XLSX.utils.sheet_to_json(sheet, {
                  header: 1,
                  raw: false,
                  defval: null,
                }) as unknown[][])
              : [];
            return {
              name,
              rows: rawRows.slice(0, MAX_WORKBOOK_ROWS).map((row) =>
                row
                  .slice(0, MAX_WORKBOOK_COLUMNS)
                  .map((cell) => primitiveWorkbookCell(cell)),
              ),
            };
          },
        );
        if (!cancelled) setSheets(nextSheets);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [bytes]);

  if (failed) {
    return (
      <ArtifactDownloadFallback
        blob={blob}
        filename={filename}
        reasonCode="office_preview_unavailable"
      />
    );
  }
  const sheet = sheets[activeSheet];
  return (
    <div className="artifact-preview-workbook">
      <div role="tablist" aria-label={t('artifact.sheetTabs')}>
        {sheets.map((candidate, index) => (
          <button
            key={`${candidate.name}:${index}`}
            type="button"
            role="tab"
            aria-selected={index === activeSheet}
            onClick={() => setActiveSheet(index)}
          >
            {candidate.name}
          </button>
        ))}
      </div>
      {sheet ? (
        <div className="artifact-preview-table-wrap">
          <table>
            <tbody>
              {sheet.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, columnIndex) => (
                    <td key={columnIndex}>{cell === null ? '' : String(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="artifact-preview-state" role="status">
          {t('artifact.emptyWorkbook')}
        </div>
      )}
    </div>
  );
}

function ArtifactDownloadFallback({
  blob,
  filename,
  reasonCode,
}: {
  blob: Blob;
  filename: string;
  reasonCode: string;
}) {
  const { t } = useI18n();
  const download = () => {
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = safeArtifactFilename(filename);
    anchor.hidden = true;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(objectUrl);
  };
  return (
    <div className="artifact-preview-state" data-reason-code={reasonCode}>
      <span>{t('artifact.previewDownloadFallback')}</span>
      <button type="button" onClick={download}>
        {t('artifact.download')}
      </button>
    </div>
  );
}

export function sanitizeArtifactHtml(source: string): string {
  const documentValue = new DOMParser().parseFromString(source, 'text/html');
  documentValue
    .querySelectorAll(
      'script, form, iframe, frame, object, embed, link, base, meta[http-equiv], input, button',
    )
    .forEach((node) => node.remove());
  sanitizeElementTree(documentValue.documentElement);
  const csp = documentValue.createElement('meta');
  csp.setAttribute('http-equiv', 'Content-Security-Policy');
  csp.setAttribute(
    'content',
    "default-src 'none'; img-src data: blob:; media-src data: blob:; style-src 'unsafe-inline'; font-src data:",
  );
  documentValue.head.prepend(csp);
  return `<!doctype html>${documentValue.documentElement.outerHTML}`;
}

export function sanitizeArtifactSvg(source: string): string | null {
  const documentValue = new DOMParser().parseFromString(source, 'image/svg+xml');
  if (
    documentValue.querySelector('parsererror') ||
    documentValue.documentElement.localName !== 'svg'
  ) {
    return null;
  }
  documentValue
    .querySelectorAll('script, foreignObject, iframe, object, embed, style')
    .forEach((node) => node.remove());
  sanitizeElementTree(documentValue.documentElement);
  return new XMLSerializer().serializeToString(documentValue.documentElement);
}

function sanitizeRenderedDocument(container: HTMLElement): void {
  container
    .querySelectorAll('script, form, iframe, frame, object, embed, link, base')
    .forEach((node) => node.remove());
  sanitizeElementTree(container);
}

function sanitizeElementTree(root: Element): void {
  for (const element of [root, ...root.querySelectorAll('*')]) {
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase();
      const value = attribute.value.trim().toLowerCase();
      if (
        name.startsWith('on') ||
        name === 'srcdoc' ||
        name === 'action' ||
        name === 'formaction' ||
        name === 'href' ||
        name === 'xlink:href' ||
        name === 'style' ||
        ((name === 'src' || name === 'poster') &&
          !value.startsWith('data:') &&
          !value.startsWith('blob:'))
      ) {
        element.removeAttribute(attribute.name);
      }
    }
  }
}

function normalizePreviewMime(value: string | undefined, filename: string): string {
  const normalized = value?.split(';', 1)[0]?.trim().toLowerCase();
  if (normalized?.includes('/')) return normalized;
  const extension = filename.split('.').at(-1)?.toLowerCase();
  const byExtension: Record<string, string> = {
    doc: 'application/msword',
    docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    html: 'text/html',
    htm: 'text/html',
    jpeg: 'image/jpeg',
    jpg: 'image/jpeg',
    mp3: 'audio/mpeg',
    mp4: 'video/mp4',
    pdf: 'application/pdf',
    png: 'image/png',
    ppt: 'application/vnd.ms-powerpoint',
    pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    svg: 'image/svg+xml',
    wav: 'audio/wav',
    webm: 'video/webm',
    xls: 'application/vnd.ms-excel',
    xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  };
  return extension ? (byExtension[extension] ?? 'application/octet-stream') : 'application/octet-stream';
}

function primitiveWorkbookCell(value: unknown): string | number | boolean | null {
  return typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean' ||
    value === null
    ? value
    : String(value);
}

function safeArtifactFilename(value: string): string {
  const leaf = value.split(/[\\/]/u).filter(Boolean).at(-1) ?? '';
  return leaf.replace(/[\u0000-\u001f<>:"/\\|?*]/gu, '_').trim() || 'artifact';
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}
