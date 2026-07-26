import { memo, useEffect, useId, useRef, useState } from 'react';
import { CheckIcon, CopyIcon, ExclamationTriangleIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import { CodeBlockFrame } from './HighlightedCode';
import {
  mermaidThemeForAppearance,
  type DesktopAppearance,
} from './mermaidDiagramModel';
import { sanitizeMermaidSvg } from './mermaidSvgSanitizer';

function appearanceFromThemeElement(element: Element | null): DesktopAppearance {
  if (!element) return 'dark';
  if (
    element.classList.contains('light') ||
    element.getAttribute('data-theme') === 'light'
  ) {
    return 'light';
  }
  return 'dark';
}

export const MermaidBlock = memo(function MermaidBlock({ chart }: { chart: string }) {
  const { t } = useI18n();
  const diagramId = `desktop-mermaid-${useId().replace(/:/g, '')}`;
  const rootRef = useRef<HTMLDivElement>(null);
  const copyResetRef = useRef<number | null>(null);
  const [appearance, setAppearance] = useState<DesktopAppearance>('dark');
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const themeElement = rootRef.current?.closest('.radix-themes') ?? document.documentElement;
    const updateAppearance = () => setAppearance(appearanceFromThemeElement(themeElement));
    updateAppearance();
    const observer = new MutationObserver(updateAppearance);
    observer.observe(themeElement, {
      attributes: true,
      attributeFilter: ['class', 'data-theme'],
    });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    setSvg(null);
    setError(null);

    async function renderChart() {
      try {
        const mermaid = (await import('mermaid')).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: mermaidThemeForAppearance(appearance),
          securityLevel: 'strict',
          htmlLabels: false,
          fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
          suppressErrorRendering: true,
        });
        const result = await mermaid.render(diagramId, chart);
        const sanitizedSvg = sanitizeMermaidSvg(result.svg);
        if (!sanitizedSvg) throw new Error('Mermaid returned an invalid SVG document.');
        if (!cancelled) setSvg(sanitizedSvg);
      } catch (cause) {
        document.getElementById(`d${diagramId}`)?.remove();
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : t('chat.mermaid.renderError'));
        }
      }
    }

    void renderChart();
    return () => {
      cancelled = true;
    };
  }, [appearance, chart, diagramId, t]);

  useEffect(() => {
    return () => {
      if (copyResetRef.current !== null) window.clearTimeout(copyResetRef.current);
    };
  }, []);

  const copySource = async () => {
    try {
      await navigator.clipboard.writeText(chart);
      setCopied(true);
      if (copyResetRef.current !== null) window.clearTimeout(copyResetRef.current);
      copyResetRef.current = window.setTimeout(() => setCopied(false), 4000);
    } catch {
      setCopied(false);
    }
  };

  if (error) {
    return (
      <div className="mermaid-block is-error" ref={rootRef} title={error}>
        <div className="mermaid-block-error" role="alert">
          <ExclamationTriangleIcon aria-hidden="true" />
          <span>{t('chat.mermaid.renderError')}</span>
        </div>
        <CodeBlockFrame code={chart} language="mermaid" />
      </div>
    );
  }

  return (
    <div className="mermaid-block" ref={rootRef}>
      <div className="mermaid-block-head">
        <span>mermaid</span>
        <button
          type="button"
          className="mermaid-block-copy"
          aria-label={
            copied ? t('chat.mermaid.copied') : t('chat.mermaid.copySource')
          }
          onClick={() => {
            void copySource();
          }}
        >
          {copied ? <CheckIcon aria-hidden="true" /> : <CopyIcon aria-hidden="true" />}
          <span>{copied ? t('chat.mermaid.copied') : t('chat.mermaid.copySource')}</span>
        </button>
      </div>
      <div
        className={`mermaid-block-canvas${svg ? ' is-ready' : ' is-loading'}`}
        aria-busy={!svg}
      >
        {svg ? (
          <div dangerouslySetInnerHTML={{ __html: svg }} />
        ) : (
          <span>{t('chat.mermaid.rendering')}</span>
        )}
      </div>
    </div>
  );
});
