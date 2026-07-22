import {
  type CSSProperties,
  type ErrorInfo,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  Component,
  memo,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';

import { useTranslation } from 'react-i18next';

import {
  ComponentNode,
  classMapToString,
  mergeClassMaps,
  stylesToObject,
  useA2UIComponent,
  useA2UIRegistry,
  useA2UIState,
  type A2UINodeLike,
} from './a2uiInternals';

import type { TFunction } from 'i18next';

interface A2UIComponentNode extends A2UINodeLike {
  id?: string;
  type?: string;
  properties?: Record<string, unknown>;
  weight?: number;
}

interface A2UIComponentProps {
  node: A2UIComponentNode;
  surfaceId: string;
}

interface A2UIRenderBoundaryProps {
  children: ReactNode;
  fallback: ReactNode;
  resetKey: unknown;
  scopeLabel: string;
}

interface A2UIRenderBoundaryState {
  hasError: boolean;
}

interface A2UIThemeShape {
  components: {
    Row: unknown;
    Column: unknown;
    List: unknown;
    Card: unknown;
    Button: unknown;
    Tabs: {
      container: unknown;
      element: unknown;
      controls: {
        all: unknown;
        selected: unknown;
      };
    };
    Modal: {
      backdrop: unknown;
      element: unknown;
    };
  };
  additionalStyles?: {
    Row?: unknown;
    Column?: unknown;
    List?: unknown;
    Card?: unknown;
    Button?: unknown;
    Tabs?: unknown;
    Modal?: unknown;
  };
}

function resolveNode(input: unknown): A2UIComponentNode | null {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    return null;
  }
  const node = input as A2UIComponentNode;
  return typeof node.type === 'string' ? node : null;
}

function getNodeKey(node: A2UIComponentNode | null, fallback: string): string {
  if (typeof node?.id === 'string' && node.id.trim().length > 0) {
    return node.id;
  }
  return fallback;
}

function resolveAxisValue(input: unknown, fallback: string): string {
  return typeof input === 'string' && input.trim().length > 0 ? input : fallback;
}

function getHostStyle(weight: number | undefined): CSSProperties | undefined {
  return weight !== undefined ? ({ '--weight': weight } as CSSProperties) : undefined;
}

function useTypedTheme(node: A2UIComponentNode, surfaceId: string): A2UIThemeShape {
  const helpers = useA2UIComponent(node, surfaceId);
  return helpers.theme as A2UIThemeShape;
}

class A2UIRenderBoundary extends Component<A2UIRenderBoundaryProps, A2UIRenderBoundaryState> {
  constructor(props: A2UIRenderBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): A2UIRenderBoundaryState {
    return { hasError: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(
      `[A2UI] Local render error in ${this.props.scopeLabel}:`,
      error,
      info.componentStack
    );
  }

  override componentDidUpdate(prevProps: A2UIRenderBoundaryProps): void {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false });
    }
  }

  override render(): ReactNode {
    if (this.state.hasError) {
      return this.props.fallback;
    }
    return this.props.children;
  }
}

const LOCAL_FALLBACK_CLASS =
  'rounded-[6px] border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-400/30 dark:bg-amber-400/10 dark:text-amber-200';

function tFallback(t: TFunction, key: string, fallback: string): string {
  const translated = t(key, fallback);
  return translated === key ? fallback : translated;
}

const InlineSectionFallback = memo<{ title: string; detail: string }>(({ title, detail }) => (
  <div className={LOCAL_FALLBACK_CLASS} role="alert">
    <p className="font-medium">{title}</p>
    <p className="mt-1 text-xs opacity-80">{detail}</p>
  </div>
));

InlineSectionFallback.displayName = 'InlineSectionFallback';

const InlineButtonFallback = memo(() => {
  const { t } = useTranslation();

  return (
    <span className="text-sm font-medium opacity-80">
      {tFallback(t, 'components.a2uiIsolated.buttonUnavailable', 'Button unavailable')}
    </span>
  );
});

InlineButtonFallback.displayName = 'InlineButtonFallback';

interface A2UIIsolatedNodeProps {
  node: A2UIComponentNode | null;
  surfaceId: string;
  scopeLabel: string;
  fallback: ReactNode;
}

const A2UIIsolatedNode = memo<A2UIIsolatedNodeProps>(
  ({ node, surfaceId, scopeLabel, fallback }) => {
    const registry = useA2UIRegistry();
    const { version } = useA2UIState();

    if (!node) {
      return null;
    }

    const resetKey = `${getNodeKey(node, scopeLabel)}:${String(version)}`;

    return (
      <A2UIRenderBoundary fallback={fallback} resetKey={resetKey} scopeLabel={scopeLabel}>
        <ComponentNode node={node} surfaceId={surfaceId} {...(registry ? { registry } : {})} />
      </A2UIRenderBoundary>
    );
  }
);

A2UIIsolatedNode.displayName = 'A2UIIsolatedNode';

export const A2UIRow = memo<A2UIComponentProps>(({ node, surfaceId }) => {
  const { t } = useTranslation();
  const theme = useTypedTheme(node, surfaceId);
  const props = node.properties ?? {};
  const alignment = resolveAxisValue(props.alignment, 'stretch');
  const distribution = resolveAxisValue(props.distribution, 'start');
  const children = Array.isArray(props.children) ? props.children : [];

  return (
    <div
      className="a2ui-row"
      data-alignment={alignment}
      data-distribution={distribution}
      style={getHostStyle(node.weight)}
    >
      <section
        className={classMapToString(theme.components.Row)}
        style={stylesToObject(theme.additionalStyles?.Row)}
      >
        {children.map((child, index) => {
          const childNode = resolveNode(child);
          return (
            <A2UIIsolatedNode
              key={getNodeKey(childNode, `row-child-${String(index)}`)}
              node={childNode}
              surfaceId={surfaceId}
              scopeLabel="row child"
              fallback={
                <InlineSectionFallback
                  title={tFallback(
                    t,
                    'components.a2uiIsolated.sectionFailed',
                    'This section could not be rendered.'
                  )}
                  detail={tFallback(
                    t,
                    'components.a2uiIsolated.rowContentAvailable',
                    'Other content in this row is still available.'
                  )}
                />
              }
            />
          );
        })}
      </section>
    </div>
  );
});

A2UIRow.displayName = 'A2UIRow';

export const A2UIColumn = memo<A2UIComponentProps>(({ node, surfaceId }) => {
  const { t } = useTranslation();
  const theme = useTypedTheme(node, surfaceId);
  const props = node.properties ?? {};
  const alignment = resolveAxisValue(props.alignment, 'stretch');
  const distribution = resolveAxisValue(props.distribution, 'start');
  const children = Array.isArray(props.children) ? props.children : [];

  return (
    <div
      className="a2ui-column"
      data-alignment={alignment}
      data-distribution={distribution}
      style={getHostStyle(node.weight)}
    >
      <section
        className={classMapToString(theme.components.Column)}
        style={stylesToObject(theme.additionalStyles?.Column)}
      >
        {children.map((child, index) => {
          const childNode = resolveNode(child);
          return (
            <A2UIIsolatedNode
              key={getNodeKey(childNode, `column-child-${String(index)}`)}
              node={childNode}
              surfaceId={surfaceId}
              scopeLabel="column child"
              fallback={
                <InlineSectionFallback
                  title={tFallback(
                    t,
                    'components.a2uiIsolated.sectionFailed',
                    'This section could not be rendered.'
                  )}
                  detail={tFallback(
                    t,
                    'components.a2uiIsolated.layoutContentAvailable',
                    'Other content in this layout is still available.'
                  )}
                />
              }
            />
          );
        })}
      </section>
    </div>
  );
});

A2UIColumn.displayName = 'A2UIColumn';

export const A2UIList = memo<A2UIComponentProps>(({ node, surfaceId }) => {
  const { t } = useTranslation();
  const theme = useTypedTheme(node, surfaceId);
  const props = node.properties ?? {};
  const direction = resolveAxisValue(props.direction, 'vertical');
  const children = Array.isArray(props.children) ? props.children : [];

  return (
    <div className="a2ui-list" data-direction={direction} style={getHostStyle(node.weight)}>
      <section
        className={classMapToString(theme.components.List)}
        style={stylesToObject(theme.additionalStyles?.List)}
      >
        {children.map((child, index) => {
          const childNode = resolveNode(child);
          return (
            <A2UIIsolatedNode
              key={getNodeKey(childNode, `list-child-${String(index)}`)}
              node={childNode}
              surfaceId={surfaceId}
              scopeLabel="list child"
              fallback={
                <InlineSectionFallback
                  title={tFallback(
                    t,
                    'components.a2uiIsolated.listItemFailed',
                    'This list item could not be rendered.'
                  )}
                  detail={tFallback(
                    t,
                    'components.a2uiIsolated.listItemsAvailable',
                    'Other items in this list are still available.'
                  )}
                />
              }
            />
          );
        })}
      </section>
    </div>
  );
});

A2UIList.displayName = 'A2UIList';

export const A2UICard = memo<A2UIComponentProps>(({ node, surfaceId }) => {
  const { t } = useTranslation();
  const theme = useTypedTheme(node, surfaceId);
  const props = node.properties ?? {};
  const rawChildren = props.children ?? (props.child ? [props.child] : []);
  const children = Array.isArray(rawChildren) ? rawChildren : [];

  return (
    <div className="a2ui-card" style={getHostStyle(node.weight)}>
      <section
        className={classMapToString(theme.components.Card)}
        style={stylesToObject(theme.additionalStyles?.Card)}
      >
        {children.map((child, index) => {
          const childNode = resolveNode(child);
          return (
            <A2UIIsolatedNode
              key={getNodeKey(childNode, `card-child-${String(index)}`)}
              node={childNode}
              surfaceId={surfaceId}
              scopeLabel="card child"
              fallback={
                <InlineSectionFallback
                  title={tFallback(
                    t,
                    'components.a2uiIsolated.cardContentFailed',
                    'This card content could not be rendered.'
                  )}
                  detail={tFallback(
                    t,
                    'components.a2uiIsolated.surfaceContentAvailable',
                    'Other content on this surface is still available.'
                  )}
                />
              }
            />
          );
        })}
      </section>
    </div>
  );
});

A2UICard.displayName = 'A2UICard';

export const A2UIButton = memo<A2UIComponentProps>(({ node, surfaceId }) => {
  const helpers = useA2UIComponent(node, surfaceId);
  const theme = helpers.theme as A2UIThemeShape;
  const props = node.properties ?? {};
  const childNode = resolveNode(props.child);
  const action = props.action;
  const buttonLabel =
    helpers.resolveString(props.ariaLabel) ??
    helpers.resolveString(props.accessibilityLabel) ??
    helpers.resolveString(props.label) ??
    helpers.resolveString(props.title) ??
    undefined;

  return (
    <div className="a2ui-button" style={getHostStyle(node.weight)}>
      <button
        type="button"
        aria-label={buttonLabel}
        title={buttonLabel}
        className={classMapToString(theme.components.Button)}
        style={stylesToObject(theme.additionalStyles?.Button)}
        onClick={() => {
          if (action) {
            helpers.sendAction(action);
          }
        }}
      >
        <A2UIIsolatedNode
          key={getNodeKey(childNode, 'button-content')}
          node={childNode}
          surfaceId={surfaceId}
          scopeLabel="button content"
          fallback={<InlineButtonFallback />}
        />
      </button>
    </div>
  );
});

A2UIButton.displayName = 'A2UIButton';

function resolveTabTitle(
  tab: Record<string, unknown> | null,
  resolveString: (value: unknown) => string | null,
  fallbackTitle: string
): string {
  const title = resolveString(tab?.title);
  return title && title.trim().length > 0 ? title : fallbackTitle;
}

const TabFallback = memo<{ title: string }>(({ title }) => <TabFallbackContent title={title} />);

const TabFallbackContent = memo<{ title: string }>(({ title }) => {
  const { t } = useTranslation();

  return (
    <InlineSectionFallback
      title={tFallback(t, 'components.a2uiIsolated.tabFailed', 'This tab could not be rendered.')}
      detail={t('components.a2uiIsolated.tabDetail', {
        defaultValue: '"{{title}}" failed to render. You can still switch to other tabs.',
        title,
      })}
    />
  );
});

TabFallback.displayName = 'TabFallback';
TabFallbackContent.displayName = 'TabFallbackContent';

export const A2UITabs = memo<A2UIComponentProps>(({ node, surfaceId }) => {
  const { t } = useTranslation();
  const helpers = useA2UIComponent(node, surfaceId);
  const theme = helpers.theme as A2UIThemeShape;
  const props = node.properties ?? {};
  const [selectedIndex, setSelectedIndex] = useState(0);
  const tabItems = Array.isArray(props.tabItems)
    ? props.tabItems.filter(
        (item): item is Record<string, unknown> =>
          !!item && typeof item === 'object' && !Array.isArray(item)
      )
    : [];
  const safeSelectedIndex = selectedIndex < tabItems.length ? selectedIndex : 0;

  const resolveTabString = (value: unknown): string | null => helpers.resolveString(value);
  const activeTab = tabItems[safeSelectedIndex] ?? null;
  const activeNode = resolveNode(activeTab?.child);
  const tabFallbackTitle = (index: number) =>
    t('components.a2uiIsolated.tabFallbackTitle', {
      defaultValue: 'Tab {{index}}',
      index: index + 1,
    });
  const activeTitle = resolveTabTitle(
    activeTab,
    resolveTabString,
    tabFallbackTitle(safeSelectedIndex)
  );

  const focusTab = (nextIndex: number) => {
    requestAnimationFrame(() => {
      document.getElementById(`${surfaceId}-tab-${String(nextIndex)}`)?.focus();
    });
  };

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const lastIndex = tabItems.length - 1;
    let nextIndex: number | null = null;

    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      nextIndex = index === lastIndex ? 0 : index + 1;
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      nextIndex = index === 0 ? lastIndex : index - 1;
    } else if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = lastIndex;
    }

    if (nextIndex === null) return;
    event.preventDefault();
    setSelectedIndex(nextIndex);
    focusTab(nextIndex);
  };

  return (
    <div className="a2ui-tabs" style={getHostStyle(node.weight)}>
      <section
        className={classMapToString(theme.components.Tabs.container)}
        style={stylesToObject(theme.additionalStyles?.Tabs)}
      >
        <div
          role="tablist"
          aria-label={activeTitle}
          className={classMapToString(theme.components.Tabs.element)}
        >
          {tabItems.map((tab, index) => {
            const title = resolveTabTitle(tab, resolveTabString, tabFallbackTitle(index));
            const isSelected = index === safeSelectedIndex;
            const tabId = `${surfaceId}-tab-${String(index)}`;
            const panelId = `${surfaceId}-tabpanel-${String(index)}`;
            const classes = isSelected
              ? mergeClassMaps(
                  theme.components.Tabs.controls.all,
                  theme.components.Tabs.controls.selected
                )
              : theme.components.Tabs.controls.all;

            return (
              <button
                key={`tab-trigger-${String(index)}`}
                id={tabId}
                type="button"
                role="tab"
                aria-selected={isSelected}
                aria-controls={panelId}
                tabIndex={isSelected ? 0 : -1}
                className={classMapToString(classes)}
                onClick={() => {
                  setSelectedIndex(index);
                }}
                onKeyDown={(event) => {
                  handleTabKeyDown(event, index);
                }}
              >
                {title}
              </button>
            );
          })}
        </div>
        <div
          id={`${surfaceId}-tabpanel-${String(safeSelectedIndex)}`}
          role="tabpanel"
          aria-labelledby={`${surfaceId}-tab-${String(safeSelectedIndex)}`}
        >
          <A2UIIsolatedNode
            key={getNodeKey(activeNode, `tab-panel-${String(safeSelectedIndex)}`)}
            node={activeNode}
            surfaceId={surfaceId}
            scopeLabel={`tab "${activeTitle}"`}
            fallback={<TabFallback title={activeTitle} />}
          />
        </div>
      </section>
    </div>
  );
});

A2UITabs.displayName = 'A2UITabs';

export const A2UIModal = memo<A2UIComponentProps>(({ node, surfaceId }) => {
  const { t } = useTranslation();
  const theme = useTypedTheme(node, surfaceId);
  const props = node.properties ?? {};
  const [isOpen, setIsOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const entryPointChild = resolveNode(props.entryPointChild);
  const contentChild = resolveNode(props.contentChild);

  const openModal = useCallback(() => {
    setIsOpen(true);
  }, []);

  const closeModal = useCallback(() => {
    setIsOpen(false);
  }, []);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) {
      return undefined;
    }

    if (isOpen && !dialog.open) {
      if (typeof dialog.showModal === 'function') {
        dialog.showModal();
      } else {
        dialog.setAttribute('open', 'true');
      }
    }

    const handleClose = () => {
      setIsOpen(false);
    };

    dialog.addEventListener('close', handleClose);
    return () => {
      dialog.removeEventListener('close', handleClose);
    };
  }, [isOpen]);

  const handleBackdropClick = useCallback(
    (event: MouseEvent<HTMLDialogElement>) => {
      if (event.target === event.currentTarget) {
        closeModal();
      }
    },
    [closeModal]
  );

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDialogElement>) => {
      if (event.key === 'Escape') {
        closeModal();
      }
    },
    [closeModal]
  );

  if (!isOpen) {
    return (
      <div className="a2ui-modal" style={getHostStyle(node.weight)}>
        <section
          role="button"
          tabIndex={0}
          onClick={openModal}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              openModal();
            }
          }}
          style={{ cursor: 'pointer' }}
        >
          {' '}
          <A2UIIsolatedNode
            key={getNodeKey(entryPointChild, 'modal-trigger')}
            node={entryPointChild}
            surfaceId={surfaceId}
            scopeLabel="modal trigger"
            fallback={
              <InlineSectionFallback
                title={tFallback(
                  t,
                  'components.a2uiIsolated.modalTriggerFailed',
                  'This modal trigger could not be rendered.'
                )}
                detail={tFallback(
                  t,
                  'components.a2uiIsolated.surfaceRestAvailable',
                  'The rest of the surface is still available.'
                )}
              />
            }
          />
        </section>
      </div>
    );
  }

  return (
    <div className="a2ui-modal" style={getHostStyle(node.weight)}>
      <dialog
        ref={dialogRef}
        className={classMapToString(theme.components.Modal.backdrop)}
        onClick={handleBackdropClick}
        onKeyDown={handleKeyDown}
      >
        <section
          className={classMapToString(theme.components.Modal.element)}
          style={stylesToObject(theme.additionalStyles?.Modal)}
        >
          <div>
            <button
              type="button"
              onClick={() => {
                closeModal();
              }}
              aria-label={tFallback(t, 'components.a2uiIsolated.closeModal', 'Close modal')}
            >
              <span className="g-icon">close</span>
            </button>
          </div>
          <A2UIIsolatedNode
            key={getNodeKey(contentChild, 'modal-content')}
            node={contentChild}
            surfaceId={surfaceId}
            scopeLabel="modal content"
            fallback={
              <InlineSectionFallback
                title={tFallback(
                  t,
                  'components.a2uiIsolated.modalContentFailed',
                  'This modal content could not be rendered.'
                )}
                detail={tFallback(
                  t,
                  'components.a2uiIsolated.modalContentDetail',
                  'Close the dialog or continue with other content.'
                )}
              />
            }
          />
        </section>
      </dialog>
    </div>
  );
});

A2UIModal.displayName = 'A2UIModal';
