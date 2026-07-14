export type ChatComposerVariant = 'workspace' | 'session';

export type ChatComposerPresentation = Readonly<{
  placeholderKey: 'session.steerComposerPlaceholder' | null;
  showCommands: boolean;
  showPaneHeader: boolean;
  showQueueHandoff: boolean;
  showRuntimeControls: boolean;
  showRuntimeStatus: boolean;
  showWorkflowStrip: boolean;
}>;

const SESSION_COMPOSER_PRESENTATION: ChatComposerPresentation = Object.freeze({
  placeholderKey: 'session.steerComposerPlaceholder',
  showCommands: false,
  showPaneHeader: false,
  showQueueHandoff: false,
  showRuntimeControls: false,
  showRuntimeStatus: false,
  showWorkflowStrip: false,
});

const WORKSPACE_COMPOSER_PRESENTATION: ChatComposerPresentation = Object.freeze({
  placeholderKey: null,
  showCommands: true,
  showPaneHeader: true,
  showQueueHandoff: true,
  showRuntimeControls: true,
  showRuntimeStatus: true,
  showWorkflowStrip: true,
});

export function chatComposerPresentation(
  variant: ChatComposerVariant,
): ChatComposerPresentation {
  return variant === 'session'
    ? SESSION_COMPOSER_PRESENTATION
    : WORKSPACE_COMPOSER_PRESENTATION;
}
