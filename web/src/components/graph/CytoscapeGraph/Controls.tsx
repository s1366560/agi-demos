/**
 * CytoscapeGraph Controls Component
 *
 * Provides toolbar controls for graph interaction.
 */

import { useEffect } from 'react';

import { useGraphContext } from './CytoscapeGraph';

// ========================================
// Props
// ========================================

interface ControlsProps {
  setCyInstance?: (cy: any) => void;
}

// ========================================
// Main Controls Component
// ========================================

export function CytoscapeGraphControls({ setCyInstance }: ControlsProps) {
  const context = useGraphContext();
  const { nodeCount, edgeCount, config, actions } = context;

  // Register cy instance callback
  useEffect(() => {
    if (setCyInstance) {
      const handler = (e: Event) => {
        setCyInstance((e as CustomEvent).detail);
      };
      window.addEventListener('cytoscape-ready', handler);
      return () => { window.removeEventListener('cytoscape-ready', handler); };
    }
    return undefined;
  }, [setCyInstance]);

  if (config.features?.showStats === false) {
    return (
      <div className="flex items-center justify-end p-4 bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
        <div className="flex items-center gap-2">
          {config.features?.enableRelayout !== false && (
            <button
              onClick={actions.relayout}
              className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              title="Relayout"
            >
              <span className="material-symbols-outlined">refresh</span>
            </button>
          )}
          <button
            onClick={actions.fitView}
            className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            title="Fit to View"
          >
            <span className="material-symbols-outlined">center_focus_strong</span>
          </button>
          <button
            onClick={actions.reloadData}
            className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            title="Reload Data"
          >
            <span className="material-symbols-outlined">sync</span>
          </button>
          {config.features?.enableExport !== false && (
            <button
              onClick={actions.exportImage}
              className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              title="Export as PNG"
            >
              <span className="material-symbols-outlined">download</span>
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between p-4 bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
          <span>Nodes:</span>
          <span className="font-semibold text-slate-900 dark:text-white">{nodeCount}</span>
        </div>
        <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
          <span>Edges:</span>
          <span className="font-semibold text-slate-900 dark:text-white">{edgeCount}</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {config.features?.enableRelayout !== false && (
          <button
            onClick={actions.relayout}
            className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            title="Relayout"
          >
            <span className="material-symbols-outlined">refresh</span>
          </button>
        )}
        <button
          onClick={actions.fitView}
          className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          title="Fit to View"
        >
          <span className="material-symbols-outlined">center_focus_strong</span>
        </button>
        <button
          onClick={actions.reloadData}
          className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          title="Reload Data"
        >
          <span className="material-symbols-outlined">sync</span>
        </button>
        {config.features?.enableExport !== false && (
          <button
            onClick={actions.exportImage}
            className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            title="Export as PNG"
          >
            <span className="material-symbols-outlined">download</span>
          </button>
        )}
      </div>
    </div>
  );
}

CytoscapeGraphControls.displayName = 'CytoscapeGraphControls';
