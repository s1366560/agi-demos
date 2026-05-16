import { createContext, useContext } from 'react';
import type { ComponentType, CSSProperties, NamedExoticComponent, ReactNode } from 'react';

// @ts-expect-error CopilotKit does not publish declarations for this internal provider module.
// prettier-ignore
import { A2UIProvider as RawA2UIProvider, useA2UIActions as rawUseA2UIActions, useA2UIState as rawUseA2UIState } from '../../../../node_modules/@copilotkit/a2ui-renderer/dist/react-renderer/core/A2UIProvider.mjs';
// @ts-expect-error CopilotKit does not publish declarations for this internal renderer module.
import RawA2UIRenderer from '../../../../node_modules/@copilotkit/a2ui-renderer/dist/react-renderer/core/A2UIRenderer.mjs';
// @ts-expect-error CopilotKit does not publish declarations for this internal component node module.
import RawComponentNode from '../../../../node_modules/@copilotkit/a2ui-renderer/dist/react-renderer/core/ComponentNode.mjs';
// @ts-expect-error CopilotKit does not publish declarations for this internal hook module.
import { useA2UIComponent as rawUseA2UIComponent } from '../../../../node_modules/@copilotkit/a2ui-renderer/dist/react-renderer/hooks/useA2UIComponent.mjs';
// @ts-expect-error CopilotKit does not publish declarations for this internal catalog module.
import { mergeClassMaps as rawMergeClassMaps } from '../../../../node_modules/@copilotkit/a2ui-renderer/dist/react-renderer/lib/utils.mjs';
// @ts-expect-error CopilotKit does not publish declarations for this internal registry module.
import { ComponentRegistry as RawComponentRegistry } from '../../../../node_modules/@copilotkit/a2ui-renderer/dist/react-renderer/registry/ComponentRegistry.mjs';
// @ts-expect-error CopilotKit does not publish declarations for this internal default catalog module.
import { initializeDefaultCatalog as rawInitializeDefaultCatalog } from '../../../../node_modules/@copilotkit/a2ui-renderer/dist/react-renderer/registry/defaultCatalog.mjs';
// @ts-expect-error CopilotKit does not publish declarations for this internal styles module.
import { injectStyles as rawInjectStyles } from '../../../../node_modules/@copilotkit/a2ui-renderer/dist/react-renderer/styles/index.mjs';
// @ts-expect-error CopilotKit does not publish declarations for this internal theme utils module.
// prettier-ignore
import { classMapToString as rawClassMapToString, stylesToObject as rawStylesToObject } from '../../../../node_modules/@copilotkit/a2ui-renderer/dist/react-renderer/theme/utils.mjs';
import { theme as rawA2UITheme } from '../../../../node_modules/@copilotkit/a2ui-renderer/dist/theme/viewer-theme.mjs';

export interface A2UINodeLike {
  id?: string;
  type?: string;
  dataContextPath?: string;
  weight?: number;
  properties?: unknown;
}

export interface A2UIActions {
  setData(node: A2UINodeLike, path: string, value: unknown, surfaceId: string): void;
  getData(node: A2UINodeLike, path: string, surfaceId: string): unknown;
  resolvePath(path: string, dataContextPath?: string): string;
  dispatch(message: unknown): void;
  processMessages(messages: unknown[]): void;
}

export interface A2UIComponentHelpers {
  theme: unknown;
  resolveString(value: unknown): string | null;
  resolveNumber(value: unknown): number | null;
  resolveBoolean(value: unknown): boolean | null;
  setValue(path: string, value: unknown): void;
  getValue(path: string): unknown;
  sendAction(action: unknown): void;
  getUniqueId(prefix: string): string;
}

type A2UIRegisteredComponent = ComponentType<never> | NamedExoticComponent<never>;

export interface A2UIComponentRegistration {
  component: A2UIRegisteredComponent;
  lazy?: boolean | undefined;
}

export interface A2UIComponentRegistry {
  has(type: string): boolean;
  register(type: string, registration: A2UIComponentRegistration): void;
  get(type: string): A2UIRegisteredComponent | null;
  getRegisteredTypes(): string[];
  clear(): void;
}

export const A2UIRegistryContext = createContext<A2UIComponentRegistry | null>(null);

export const ComponentRegistry = RawComponentRegistry as unknown as {
  new (): A2UIComponentRegistry;
  getInstance(): A2UIComponentRegistry;
  resetInstance(): void;
};
export const useA2UIActions = rawUseA2UIActions as () => A2UIActions;
export const useA2UIState = rawUseA2UIState as () => { version: number };
export const useA2UIComponent = rawUseA2UIComponent as (
  node: A2UINodeLike,
  surfaceId: string
) => A2UIComponentHelpers;
export const A2UIProvider = RawA2UIProvider as ComponentType<{
  onAction?: ((message: unknown) => void) | null | undefined;
  theme: unknown;
  children: ReactNode;
}>;
export const A2UIRenderer = RawA2UIRenderer as ComponentType<{
  surfaceId: string;
  className?: string | undefined;
  fallback?: ReactNode | undefined;
  loadingFallback?: ReactNode | undefined;
  registry?: A2UIComponentRegistry | undefined;
}>;
export const ComponentNode = RawComponentNode as ComponentType<{
  node: A2UINodeLike | null;
  surfaceId: string;
  registry?: A2UIComponentRegistry | undefined;
}>;
export const initializeDefaultCatalog = rawInitializeDefaultCatalog as () => void;
export const injectA2UIStyles = rawInjectStyles as () => void;
export const a2uiTheme = rawA2UITheme as unknown;
export const classMapToString = rawClassMapToString as (input: unknown) => string;
export const stylesToObject = rawStylesToObject as (input: unknown) => CSSProperties;
export const mergeClassMaps = rawMergeClassMaps as (left: unknown, right: unknown) => unknown;
export const useA2UIRegistry = (): A2UIComponentRegistry | null => useContext(A2UIRegistryContext);
