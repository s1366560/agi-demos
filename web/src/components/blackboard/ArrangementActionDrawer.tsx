import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Bot, ExternalLink, Move, Route, Trash2, User } from 'lucide-react';

import { COLOR_SWATCHS, getNodeLabel } from './arrangementUtils';

import type { TopologyNode, WorkspaceAgent } from '@/types/workspace';

import type { SelectionState } from './arrangementUtils';

interface ArrangementActionDrawerProps {
  selection: SelectionState | null;
  selectedAgent: WorkspaceAgent | null;
  selectedNode: TopologyNode | null;
  selectedHex: { q: number; r: number } | null;
  agentWorkspacePath: string;
  pendingAction: string | null;
  labelDraft: string;
  colorDraft: string;
  setLabelDraft: (v: string) => void;
  setColorDraft: (v: string) => void;
  setAddAgentOpen: (v: boolean) => void;
  onOpenBlackboard: () => void;
  handleCreateNode: (nodeType: TopologyNode['node_type']) => Promise<void>;
  handleSaveSelection: () => Promise<void>;
  handleDeleteSelection: () => Promise<void>;
  beginMoveMode: () => void;
  moveMode: unknown;
}

export function ArrangementActionDrawer({
  selection,
  selectedAgent,
  selectedNode,
  selectedHex,
  agentWorkspacePath,
  pendingAction,
  labelDraft,
  colorDraft,
  setLabelDraft,
  setColorDraft,
  setAddAgentOpen,
  onOpenBlackboard,
  handleCreateNode,
  handleSaveSelection,
  handleDeleteSelection,
  beginMoveMode,
  moveMode,
}: ArrangementActionDrawerProps) {
  const { t } = useTranslation();

  return (
    <div className="mt-4 flex-shrink-0 rounded-[24px] border border-border-light bg-surface-muted p-4 dark:border-border-dark dark:bg-surface-dark-alt">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-sm font-medium text-text-primary dark:text-text-inverse">
            {selection?.kind === 'agent' && selectedAgent
              ? (selectedAgent.label ?? selectedAgent.display_name ?? selectedAgent.agent_id)
              : selection?.kind === 'node' && selectedNode
                ? getNodeLabel(
                    selectedNode,
                    selectedNode.node_type === 'human_seat'
                      ? t('blackboard.arrangement.defaults.humanSeat', 'Human seat')
                      : t('blackboard.arrangement.defaults.corridor', 'Corridor')
                  )
                : selection?.kind === 'blackboard'
                  ? t('blackboard.arrangement.centerTitle', 'Central blackboard')
                  : selection?.kind === 'empty'
                    ? t('blackboard.arrangement.emptySlot', 'Empty workstation')
                    : t('blackboard.arrangement.drawerTitle', 'Action drawer')}
          </div>
          <div className="mt-1 text-xs text-text-muted dark:text-text-muted">
            {selectedHex
              ? t('blackboard.arrangement.coordinates', 'Hex {{q}}, {{r}}', selectedHex)
              : t(
                  'blackboard.arrangement.drawerSubtitle',
                  'Selection-aware actions appear here so the grid stays focused.'
                )}
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {selection?.kind === 'blackboard' && (
            <button
              type="button"
              onClick={onOpenBlackboard}
              className="inline-flex min-h-10 items-center rounded-lg border border-primary/20 bg-primary/10 px-4 text-sm font-medium text-primary transition-colors motion-reduce:transition-none hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:text-primary-200"
            >
              {t('blackboard.openBoard', 'Open central blackboard')}
            </button>
          )}

          {selection?.kind === 'agent' && (
            <>
              <Link
                to={agentWorkspacePath}
                className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-border-light bg-surface-light px-4 text-sm font-medium text-text-primary transition-colors motion-reduce:transition-none hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-elevated"
              >
                <ExternalLink className="h-4 w-4" />
                {t('blackboard.arrangement.openWorkspace', 'Open workspace')}
              </Link>
              <button
                type="button"
                onClick={beginMoveMode}
                className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-border-light bg-surface-light px-4 text-sm font-medium text-text-primary transition-colors motion-reduce:transition-none hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-elevated"
              >
                <Move className="h-4 w-4" />
                {t('blackboard.arrangement.actions.move', 'Move')}
              </button>
              <button
                type="button"
                onClick={() => {
                  void handleDeleteSelection();
                }}
                disabled={pendingAction != null}
                className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-error/25 bg-error/10 px-4 text-sm font-medium text-status-text-error dark:text-status-text-error-dark transition-colors motion-reduce:transition-none hover:bg-error/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Trash2 className="h-4 w-4" />
                {t('blackboard.arrangement.actions.remove', 'Remove')}
              </button>
            </>
          )}

          {selection?.kind === 'node' && (
            <>
              <button
                type="button"
                onClick={beginMoveMode}
                className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-border-light bg-surface-light px-4 text-sm font-medium text-text-primary transition-colors motion-reduce:transition-none hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-elevated"
              >
                <Move className="h-4 w-4" />
                {t('blackboard.arrangement.actions.move', 'Move')}
              </button>
              <button
                type="button"
                onClick={() => {
                  void handleDeleteSelection();
                }}
                disabled={pendingAction != null}
                className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-error/25 bg-error/10 px-4 text-sm font-medium text-status-text-error dark:text-status-text-error-dark transition-colors motion-reduce:transition-none hover:bg-error/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Trash2 className="h-4 w-4" />
                {t('blackboard.arrangement.actions.remove', 'Remove')}
              </button>
            </>
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-col gap-4">
        <div className="space-y-4">
          {selection?.kind === 'empty' && (
            <div className="grid gap-3 sm:grid-cols-3">
              <button
                type="button"
                onClick={() => {
                  setAddAgentOpen(true);
                }}
                className="flex min-h-[96px] flex-col justify-between rounded-lg border border-border-light bg-surface-light p-4 text-left transition-colors motion-reduce:transition-none hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark dark:hover:bg-surface-elevated"
              >
                <Bot className="h-5 w-5 text-primary dark:text-primary-300" />
                <div>
                  <div className="text-sm font-medium text-text-primary dark:text-text-inverse">
                    {t('blackboard.arrangement.actions.addAgent', 'Add AI employee')}
                  </div>
                  <div className="mt-1 text-xs leading-5 text-text-secondary dark:text-text-muted">
                    {t(
                      'blackboard.arrangement.actions.addAgentHint',
                      'Bind an agent definition directly onto this hex.'
                    )}
                  </div>
                </div>
              </button>

              <button
                type="button"
                onClick={() => {
                  void handleCreateNode('corridor');
                }}
                className="flex min-h-[96px] flex-col justify-between rounded-lg border border-border-light bg-surface-light p-4 text-left transition-colors motion-reduce:transition-none hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark dark:hover:bg-surface-elevated"
              >
                <Route className="h-5 w-5 text-info dark:text-status-text-info-dark" />
                <div>
                  <div className="text-sm font-medium text-text-primary dark:text-text-inverse">
                    {t('blackboard.arrangement.actions.addCorridor', 'Place corridor')}
                  </div>
                  <div className="mt-1 text-xs leading-5 text-text-secondary dark:text-text-muted">
                    {t(
                      'blackboard.arrangement.actions.addCorridorHint',
                      'Reserve this slot for coordination or routing structure.'
                    )}
                  </div>
                </div>
              </button>

              <button
                type="button"
                onClick={() => {
                  void handleCreateNode('human_seat');
                }}
                className="flex min-h-[96px] flex-col justify-between rounded-lg border border-border-light bg-surface-light p-4 text-left transition-colors motion-reduce:transition-none hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark dark:hover:bg-surface-elevated"
              >
                <User className="h-5 w-5 text-warning dark:text-status-text-warning-dark" />
                <div>
                  <div className="text-sm font-medium text-text-primary dark:text-text-inverse">
                    {t('blackboard.arrangement.actions.addHumanSeat', 'Place human seat')}
                  </div>
                  <div className="mt-1 text-xs leading-5 text-text-secondary dark:text-text-muted">
                    {t(
                      'blackboard.arrangement.actions.addHumanSeatHint',
                      'Mark a human-operated slot for collaboration or review.'
                    )}
                  </div>
                </div>
              </button>
            </div>
          )}

          {(selection?.kind === 'agent' || selection?.kind === 'node') && (
            <div className="rounded-lg border border-border-light bg-surface-light p-4 dark:border-border-dark dark:bg-surface-dark">
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="space-y-2 text-sm text-text-primary dark:text-text-secondary">
                  <span className="text-xs uppercase tracking-wider text-text-muted dark:text-text-muted">
                    {selection.kind === 'agent'
                      ? t('blackboard.arrangement.fields.agentLabel', 'Display label')
                      : t('blackboard.arrangement.fields.nodeLabel', 'Seat label')}
                  </span>
                  <input
                    value={labelDraft}
                    onChange={(event) => {
                      setLabelDraft(event.target.value);
                    }}
                    maxLength={64}
                    className="min-h-11 w-full rounded-lg border border-border-light bg-surface-muted px-4 text-sm text-text-primary outline-none transition focus:border-primary/60 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-inverse focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                    placeholder={t(
                      'blackboard.arrangement.fields.labelPlaceholder',
                      'Name this workstation'
                    )}
                  />
                </label>

                <div className="space-y-2 text-sm text-text-primary dark:text-text-secondary">
                  <div className="text-xs uppercase tracking-wider text-text-muted dark:text-text-muted">
                    {t('blackboard.arrangement.fields.accentColor', 'Accent color')}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {COLOR_SWATCHS.map((swatch) => (
                      <button
                        key={swatch}
                        type="button"
                        aria-label={t('blackboard.arrangement.fields.pickColor', 'Pick color')}
                        onClick={() => {
                          setColorDraft(swatch);
                        }}
                        className={`h-10 w-10 rounded-lg border transition motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ${
                          colorDraft === swatch
                            ? 'border-transparent ring-2 ring-white ring-offset-2 ring-offset-surface-dark'
                            : 'border-white/10 hover:border-white/30'
                        }`}
                        style={{ backgroundColor: swatch }}
                      />
                    ))}
                  </div>
                </div>
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => {
                    void handleSaveSelection();
                  }}
                  disabled={pendingAction != null}
                  className="min-h-11 rounded-lg bg-primary px-5 text-sm font-medium text-slate-50 transition-colors motion-reduce:transition-none hover:bg-primary-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {pendingAction === 'save-agent' || pendingAction === 'save-node'
                    ? t('common.loading', 'Loading…')
                    : t('blackboard.save', 'Save')}
                </button>

                {selection.kind === 'agent' && selectedAgent?.status && (
                  <span className="rounded-full border border-border-light bg-surface-muted px-3 py-2 text-xs text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-secondary">
                    {t('blackboard.arrangement.fields.status', 'Status')}: {selectedAgent.status}
                  </span>
                )}
              </div>
            </div>
          )}

          {selection == null && (
            <div className="rounded-lg border border-dashed border-border-separator bg-surface-light p-4 text-sm leading-7 text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
              {t(
                'blackboard.arrangement.drawerEmpty',
                'Use the grid to stage a layout. The action drawer adapts to the selected workstation and keeps destructive actions away from the canvas.'
              )}
            </div>
          )}
        </div>

        <p className="px-4 text-xs text-text-muted dark:text-text-muted">
          {selection?.kind === 'blackboard'
            ? t(
                'blackboard.arrangement.context.blackboard',
                'The central hex opens the full blackboard modal, where discussions, notes, and delivery state stay together.'
              )
            : selection?.kind === 'empty'
              ? t(
                  'blackboard.arrangement.context.empty',
                  'This hex is free. Use it to place a new agent, reserve a human seat, or carve a corridor into the command floor.'
                )
              : selection?.kind === 'agent'
                ? t(
                    'blackboard.arrangement.context.agent',
                    'Agents keep their own workspace binding id, so layout moves stay synced with the workspace roster and real-time events.'
                  )
                : selection?.kind === 'node'
                  ? t(
                      'blackboard.arrangement.context.node',
                      'Topology nodes are persisted separately from agent bindings, which keeps human seats and corridor structure editable without disturbing execution bindings.'
                    )
                  : t(
                      'blackboard.arrangement.context.none',
                      'No hex selected yet. Pick a slot to inspect its available actions.'
                    )}{' '}
          {moveMode
            ? t(
                'blackboard.arrangement.context.move',
                'A move is armed. Select any free hex outside the center slot to complete it.'
              )
            : t(
                'blackboard.arrangement.context.sync',
                'Topology changes also stream back in real time. If another collaborator edits this workspace, the grid will reconcile from the event snapshot.'
              )}
        </p>
      </div>
    </div>
  );
}
