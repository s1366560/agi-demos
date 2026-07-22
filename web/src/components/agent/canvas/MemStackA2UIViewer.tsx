import { memo, useEffect, useId, useMemo, useRef } from 'react';

import { useTranslation } from 'react-i18next';

import { type A2UIViewerProps } from '@copilotkit/a2ui-renderer';

import {
  A2UIProvider,
  A2UIRenderer,
  A2UIRegistryContext,
  a2uiTheme,
  injectA2UIStyles,
  useA2UIActions,
} from './a2uiInternals';
import { createMemStackA2UIRegistry } from './A2UIMemStackRegistry';

let stylesInjected = false;

function ensureA2UIStyles(): void {
  if (!stylesInjected) {
    injectA2UIStyles();
    stylesInjected = true;
  }
}

function objectToValueMaps(obj: Record<string, unknown>): Array<Record<string, unknown>> {
  return Object.entries(obj).map(([key, value]) => valueToValueMap(key, value));
}

function valueToValueMap(key: string, value: unknown): Record<string, unknown> {
  if (typeof value === 'string') {
    return { key, valueString: value };
  }
  if (typeof value === 'number') {
    return { key, valueNumber: value };
  }
  if (typeof value === 'boolean') {
    return { key, valueBoolean: value };
  }
  if (value === null || value === undefined) {
    return { key };
  }
  if (Array.isArray(value)) {
    return {
      key,
      valueMap: value.map((item, index) => valueToValueMap(String(index), item)),
    };
  }
  if (typeof value === 'object') {
    return {
      key,
      valueMap: objectToValueMaps(value as Record<string, unknown>),
    };
  }
  return { key };
}

function toOptionalString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function buildViewerSurfaceId(
  baseId: string,
  root: string,
  components: A2UIViewerProps['components']
): string {
  const definitionKey = `${root}-${JSON.stringify(components)}`;
  let hash = 0;
  for (let index = 0; index < definitionKey.length; index += 1) {
    const charCode = definitionKey.charCodeAt(index);
    hash = (hash << 5) - hash + charCode;
    hash &= hash;
  }
  return `surface${baseId.replace(/:/g, '-')}${String(hash)}`;
}

const EmptyFallback = memo<{ className?: string | undefined }>(({ className }) => {
  const { t } = useTranslation();
  return (
    <div
      className={className}
      style={{
        padding: 16,
        color: '#666',
        fontFamily: 'system-ui',
      }}
    >
      {t('components.a2uiViewer.noContent', { defaultValue: 'No content to display' })}
    </div>
  );
});

EmptyFallback.displayName = 'EmptyFallback';

interface MemStackA2UIViewerInnerProps {
  resolvedSurfaceId: string;
  root: string;
  components: A2UIViewerProps['components'];
  data?: A2UIViewerProps['data'] | undefined;
  styles?: A2UIViewerProps['styles'] | undefined;
  className?: string | undefined;
  registry: ReturnType<typeof createMemStackA2UIRegistry>;
}

const MemStackA2UIViewerInner = memo<MemStackA2UIViewerInnerProps>(
  ({ resolvedSurfaceId, root, components, data, styles, className, registry }) => {
    const actions = useA2UIActions();
    const lastProcessedRef = useRef('');

    useEffect(() => {
      const normalizedData = data ?? {};
      const renderKey = `${resolvedSurfaceId}-${JSON.stringify(components)}-${JSON.stringify(normalizedData)}`;
      if (renderKey === lastProcessedRef.current) {
        return;
      }

      lastProcessedRef.current = renderKey;

      const messages: Array<Record<string, unknown>> = [
        {
          beginRendering: {
            surfaceId: resolvedSurfaceId,
            root,
            styles: styles ?? {},
          },
        },
        {
          surfaceUpdate: {
            surfaceId: resolvedSurfaceId,
            components,
          },
        },
      ];

      if (Object.keys(normalizedData).length > 0) {
        const contents = objectToValueMaps(normalizedData);
        if (contents.length > 0) {
          messages.push({
            dataModelUpdate: {
              surfaceId: resolvedSurfaceId,
              path: '/',
              contents,
            },
          });
        }
      }

      actions.processMessages(messages);
    }, [actions, components, data, resolvedSurfaceId, root, styles]);

    return (
      <div className={className}>
        <A2UIRenderer surfaceId={resolvedSurfaceId} registry={registry} />
      </div>
    );
  }
);

MemStackA2UIViewerInner.displayName = 'MemStackA2UIViewerInner';

export const MemStackA2UIViewer = memo<A2UIViewerProps>(
  ({ root, components, data, onAction, styles, className }) => {
    ensureA2UIStyles();

    const baseId = useId();
    const registry = useMemo(() => createMemStackA2UIRegistry(), []);
    const resolvedSurfaceId = useMemo(
      () => buildViewerSurfaceId(baseId, root, components),
      [baseId, components, root]
    );
    const handleAction = useMemo(() => {
      if (!onAction) {
        return null;
      }
      return (message: unknown) => {
        const userAction =
          message && typeof message === 'object' && 'userAction' in message
            ? (message as { userAction?: Record<string, unknown> }).userAction
            : undefined;
        if (!userAction) {
          return;
        }
        onAction({
          actionName: toOptionalString(userAction.name),
          sourceComponentId: toOptionalString(userAction.sourceComponentId),
          timestamp: toOptionalString(userAction.timestamp),
          context:
            userAction.context && typeof userAction.context === 'object'
              ? (userAction.context as Record<string, unknown>)
              : {},
        });
      };
    }, [onAction]);

    const isEmpty = Array.isArray(components)
      ? components.length === 0
      : Object.keys(components as Record<string, unknown>).length === 0;

    if (isEmpty) {
      return <EmptyFallback className={className} />;
    }

    return (
      <A2UIRegistryContext.Provider value={registry}>
        <A2UIProvider onAction={handleAction} theme={a2uiTheme}>
          <MemStackA2UIViewerInner
            resolvedSurfaceId={resolvedSurfaceId}
            root={root}
            components={components}
            data={data}
            styles={styles}
            className={className}
            registry={registry}
          />
        </A2UIProvider>
      </A2UIRegistryContext.Provider>
    );
  }
);

MemStackA2UIViewer.displayName = 'MemStackA2UIViewer';
