/**
 * MermaidBlock - Renders mermaid diagram code as SVG
 *
 * Lazy-initializes mermaid and renders charts client-side.
 * Falls back to showing raw code on render failure.
 */

import { memo, useEffect, useRef, useState, useId } from 'react';

import { Copy, Check } from 'lucide-react';

export const MermaidBlock = memo<{ chart: string }>(({ chart }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const uniqueId = `mermaid-${useId().replace(/:/g, '')}`;

  useEffect(() => {
    let cancelled = false;

    async function renderChart() {
      try {
        const mermaid = (await import('mermaid')).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: document.documentElement.classList.contains('dark') ? 'dark' : 'default',
          securityLevel: 'strict',
          fontFamily: 'Inter, system-ui, sans-serif',
          suppressErrorRendering: true,
        });

        const { svg } = await mermaid.render(uniqueId, chart);
        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg;
          setError(null);
        }
      } catch (e) {
        // Clean up any error elements mermaid may have injected into the DOM
        const errElement = document.getElementById('d' + uniqueId);
        if (errElement) {
          errElement.remove();
        }
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Mermaid render failed');
        }
      }
    }

    renderChart();
    return () => {
      cancelled = true;
    };
  }, [chart, uniqueId]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(chart);
      setCopied(true);
      setTimeout(() => { setCopied(false); }, 2000);
    } catch {
      // silent fail
    }
  };

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 dark:border-red-800 overflow-hidden my-3">
        <div className="px-3 py-1.5 bg-red-50 dark:bg-red-900/30 text-xs text-red-600 dark:text-red-400">
          Mermaid render error
        </div>
        <pre className="p-4 text-sm overflow-x-auto bg-slate-50 dark:bg-slate-800">
          <code>{chart}</code>
        </pre>
      </div>
    );
  }

  return (
    <div className="group/mermaid relative rounded-lg border border-slate-200 dark:border-slate-600 overflow-hidden my-3">
      <div className="flex items-center justify-between px-3 py-1.5 bg-slate-200/80 dark:bg-slate-700/80">
        <span className="text-xs font-medium text-slate-500 dark:text-slate-400 select-none">
          mermaid
        </span>
        <button
          type="button"
          onClick={handleCopy}
          className="p-1 rounded hover:bg-slate-300/60 dark:hover:bg-slate-600/60 transition-colors text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
          title={copied ? 'Copied!' : 'Copy source'}
        >
          {copied ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
        </button>
      </div>
      <div
        ref={containerRef}
        className="flex justify-center p-4 bg-white dark:bg-slate-900 overflow-x-auto [&>svg]:max-w-full"
      />
    </div>
  );
});

MermaidBlock.displayName = 'MermaidBlock';
