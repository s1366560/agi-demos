import type { ComponentType } from 'react';

export type A2UIRuntimeNode = {
  id: string;
  type: string;
  properties: Record<string, unknown>;
  dataContextPath?: string;
  weight?: number;
};

export type A2UIRuntimeComponentProps = {
  node: A2UIRuntimeNode;
  surfaceId: string;
};

export type A2UIRuntimeHelpers = {
  resolveString(value: unknown): string | null;
  resolveNumber(value: unknown): number | null;
  resolveBoolean(value: unknown): boolean | null;
  setValue(path: string, value: unknown): void;
  getValue(path: string): unknown;
  sendAction(action: unknown): void;
  getUniqueId(prefix: string): string;
};

export class ComponentRegistry {
  static getInstance(): ComponentRegistry;
  register(
    type: string,
    registration: { component: ComponentType<A2UIRuntimeComponentProps> },
  ): void;
  unregister(type: string): void;
  has(type: string): boolean;
  getRegisteredTypes(): string[];
}

export function useA2UIComponent(
  node: A2UIRuntimeNode,
  surfaceId: string,
): A2UIRuntimeHelpers;
