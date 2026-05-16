/**
 * CytoscapeGraph Controls Component
 *
 * Provides toolbar controls for graph interaction.
 */

import { useEffect } from 'react';

import { useTranslation } from 'react-i18next';

import { RefreshCw, Focus, RefreshCcw, Download } from 'lucide-react';

import { useGraphContext } from './CytoscapeGraph';

import type cytoscape from 'cytoscape';
import type { TFunction } from 'i18next';

// ========================================
// Props
// ========================================

interface ControlsProps {
  setCyInstance?: ((cy: cytoscape.Core) => void) | undefined;
}

function tFallback(t: TFunction, key: string, fallback: string): string {
  const translated = t(key, fallback);
  return translated === key ? fallback : translated;
}

// ========================================
// Main Controls Component
// ========================================

export function CytoscapeGraphControls({ setCyInstance }: ControlsProps) {
  const { t } = useTranslation();
  const context = useGraphContext();
  const { nodeCount, edgeCount, config, actions } = context;
  const features = config.features ?? {};
  const relayoutLabel = tFallback(t, 'project.graph.cytoscapeControls.relayout', 'Relayout');
  const fitToViewLabel = tFallback(t, 'project.graph.cytoscapeControls.fitToView', 'Fit to View');
  const reloadDataLabel = tFallback(t, 'project.graph.cytoscapeControls.reloadData', 'Reload Data');
  const exportPngLabel = tFallback(t, 'project.graph.cytoscapeControls.exportPng', 'Export as PNG');

  // Register cy instance callback
  useEffect(() => {
    if (setCyInstance) {
      const handler = (e: Event) => {
        setCyInstance((e as CustomEvent<cytoscape.Core>).detail);
      };
      window.addEventListener('cytoscape-ready', handler);
      return () => {
        window.removeEventListener('cytoscape-ready', handler);
      };
    }
    return undefined;
  }, [setCyInstance]);

  if (features.showStats === false) {
    return (
      <div className="flex items-center justify-end p-4 bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
        <div className="flex items-center gap-2">
          {features.enableRelayout !== false && (
            <button
              type="button"
              onClick={actions.relayout}
              className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              title={relayoutLabel}
              aria-label={relayoutLabel}
            >
              <RefreshCw size={20} />
            </button>
          )}
          <button
            type="button"
            onClick={actions.fitView}
            className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            title={fitToViewLabel}
            aria-label={fitToViewLabel}
          >
            <Focus size={20} />
          </button>
          <button
            type="button"
            onClick={actions.reloadData}
            className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            title={reloadDataLabel}
            aria-label={reloadDataLabel}
          >
            <RefreshCcw size={20} />
          </button>
          {features.enableExport !== false && (
            <button
              type="button"
              onClick={actions.exportImage}
              className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              title={exportPngLabel}
              aria-label={exportPngLabel}
            >
              <Download size={20} />
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 border-b border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
          <span>{tFallback(t, 'project.graph.cytoscapeControls.nodes', 'Nodes')}:</span>
          <span className="font-semibold text-slate-900 dark:text-white">{nodeCount}</span>
        </div>
        <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
          <span>{tFallback(t, 'project.graph.cytoscapeControls.edges', 'Edges')}:</span>
          <span className="font-semibold text-slate-900 dark:text-white">{edgeCount}</span>
        </div>
      </div>

      <div className="flex items-center gap-2 self-end sm:self-auto">
        {config.features?.enableRelayout !== false && (
          <button
            type="button"
            onClick={actions.relayout}
            className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            title={relayoutLabel}
            aria-label={relayoutLabel}
          >
            <RefreshCw size={20} />
          </button>
        )}
        <button
          type="button"
          onClick={actions.fitView}
          className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          title={fitToViewLabel}
          aria-label={fitToViewLabel}
        >
          <Focus size={20} />
        </button>
        <button
          type="button"
          onClick={actions.reloadData}
          className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          title={reloadDataLabel}
          aria-label={reloadDataLabel}
        >
          <RefreshCcw size={20} />
        </button>
        {config.features?.enableExport !== false && (
          <button
            type="button"
            onClick={actions.exportImage}
            className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            title={exportPngLabel}
            aria-label={exportPngLabel}
          >
            <Download size={20} />
          </button>
        )}
      </div>
    </div>
  );
}

CytoscapeGraphControls.displayName = 'CytoscapeGraphControls';
