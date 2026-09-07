import type { DesktopRuntimeConfig } from '../../types';

export type TemplatesRouteScope = Readonly<{
  authority: DesktopRuntimeConfig['mode'];
  tenantId: string;
}>;

export type TemplatesRouteQuery = Readonly<{
  page?: number;
  pageSize?: number;
  category?: string;
  search?: string;
}>;

export type TemplatesRouteSummary = Readonly<{
  id: string;
  tenant_id: string;
  name: string;
  version: string;
  display_name: string | null;
  description: string | null;
  category: string;
  tags: readonly string[];
  author: string | null;
  is_builtin: boolean;
  is_published: boolean;
  install_count: number;
  rating: number;
  created_at: string | null;
  updated_at: string | null;
}>;

export type TemplatesRouteDetail = TemplatesRouteSummary &
  Readonly<{
    system_prompt: string;
    trigger_description: string;
    trigger_keywords: readonly string[];
    trigger_examples: readonly string[];
    model: string;
    max_tokens: number;
    temperature: number;
    max_iterations: number;
    allowed_tools: readonly string[];
    metadata: Readonly<Record<string, unknown>> | null;
  }>;

export type TemplatesRouteObservation = Readonly<{
  scope: TemplatesRouteScope;
  authority: DesktopRuntimeConfig['mode'];
  availability: 'available';
  reasonCode: null;
  allowedActions: readonly string[];
  itemCount: number;
  templates: readonly TemplatesRouteSummary[];
  categories: readonly string[];
  total: number;
  page: number;
  pageSize: number;
}>;

export type TemplatesRouteClient = Readonly<{
  observe(
    scope: TemplatesRouteScope,
    query?: TemplatesRouteQuery,
    signal?: AbortSignal,
  ): Promise<TemplatesRouteObservation>;
  get(
    scope: TemplatesRouteScope,
    templateId: string,
    signal?: AbortSignal,
  ): Promise<TemplatesRouteDetail>;
  install(scope: TemplatesRouteScope, templateId: string, signal?: AbortSignal): Promise<void>;
  seed(scope: TemplatesRouteScope, signal?: AbortSignal): Promise<number>;
}>;
