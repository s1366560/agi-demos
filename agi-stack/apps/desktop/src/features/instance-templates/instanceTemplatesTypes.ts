export type InstanceTemplatesAuthority = 'cloud' | 'local';

export type InstanceTemplatesScope = Readonly<{
  authority: InstanceTemplatesAuthority;
  tenantId: string;
}>;

export type InstanceTemplatesQuery = Readonly<{
  page?: number;
  pageSize?: number;
  search?: string;
  status?: 'all' | 'published' | 'draft';
  isPublished?: boolean;
}>;

export type InstanceTemplatesNormalizedQuery = Readonly<{
  page: number;
  pageSize: number;
  search: string;
  status: 'all' | 'published' | 'draft';
}>;

export type InstanceTemplateSummary = Readonly<{
  id: string;
  name: string;
  slug: string;
  tenantId: string | null;
  description: string | null;
  icon: string | null;
  imageVersion: string | null;
  defaultConfig: Readonly<Record<string, unknown>>;
  isPublished: boolean;
  isFeatured: boolean;
  installCount: number;
  createdAt: string;
  updatedAt: string | null;
}>;

export type InstanceTemplateItem = Readonly<{
  id: string;
  templateId: string;
  itemType: string;
  itemSlug: string;
  displayOrder: number;
  createdAt: string;
}>;

export type InstanceTemplateCreateInput = Readonly<{
  name: string;
  slug: string;
  description: string | null;
  defaultConfig: Readonly<Record<string, unknown>>;
}>;

export type InstanceTemplatesPage = Readonly<{
  templates: readonly InstanceTemplateSummary[];
  total: number;
  page: number;
  pageSize: number;
}>;

export type InstanceTemplatesRequestOptions = Readonly<{
  signal?: AbortSignal;
}>;

export type InstanceTemplatesClient = Readonly<{
  list(
    scope: InstanceTemplatesScope,
    query?: InstanceTemplatesQuery,
    options?: InstanceTemplatesRequestOptions,
  ): Promise<InstanceTemplatesPage>;
  get(
    scope: InstanceTemplatesScope,
    templateId: string,
    options?: InstanceTemplatesRequestOptions,
  ): Promise<InstanceTemplateSummary>;
  listItems(
    scope: InstanceTemplatesScope,
    templateId: string,
    options?: InstanceTemplatesRequestOptions,
  ): Promise<readonly InstanceTemplateItem[]>;
  create(
    scope: InstanceTemplatesScope,
    input: InstanceTemplateCreateInput,
    options?: InstanceTemplatesRequestOptions,
  ): Promise<InstanceTemplateSummary>;
  delete(
    scope: InstanceTemplatesScope,
    templateId: string,
    options?: InstanceTemplatesRequestOptions,
  ): Promise<void>;
  publish(
    scope: InstanceTemplatesScope,
    templateId: string,
    options?: InstanceTemplatesRequestOptions,
  ): Promise<InstanceTemplateSummary>;
  clone(
    scope: InstanceTemplatesScope,
    templateId: string,
    newName: string,
    options?: InstanceTemplatesRequestOptions,
  ): Promise<InstanceTemplateSummary>;
}>;

export type InstanceTemplatesResourceState =
  | 'loading'
  | 'ready'
  | 'empty'
  | 'stale'
  | 'error'
  | 'conflict'
  | 'forbidden'
  | 'unavailable';

export type InstanceTemplatesDetailState =
  | 'idle'
  | 'loading'
  | 'ready'
  | 'error'
  | 'conflict'
  | 'forbidden'
  | 'unavailable';

export type InstanceTemplatesMutationState =
  | 'idle'
  | 'submitting'
  | 'error'
  | 'conflict'
  | 'forbidden'
  | 'unavailable';

export type InstanceTemplatesModel = Readonly<{
  scope: InstanceTemplatesScope;
  authority: InstanceTemplatesAuthority;
  state: InstanceTemplatesResourceState;
  reasonCode: string;
  retryVisible: boolean;
  allowedActions: readonly string[];
  templates: readonly InstanceTemplateSummary[];
  visibleTemplates: readonly InstanceTemplateSummary[];
  total: number;
  query: InstanceTemplatesNormalizedQuery;
  selectedTemplate: InstanceTemplateSummary | null;
  detailState: InstanceTemplatesDetailState;
  detailReasonCode: string | null;
  items: readonly InstanceTemplateItem[];
  mutationState: InstanceTemplatesMutationState;
  mutationReasonCode: string | null;
  lastUpdatedAt: string | null;
}>;
