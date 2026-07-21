/**
 * EdgeTypeList Compound Component
 *
 * A compound component pattern for managing Edge Types with modular sub-components.
 *
 * @example
 * ```tsx
 * import { EdgeTypeList } from './EdgeTypeList';
 *
 * <EdgeTypeList />
 * ```
 */

import React, { useCallback, useEffect, useState, useMemo, useContext } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { message } from 'antd';
import {
  Plus,
  Search,
  Download,
  Code,
  Info,
  Pencil,
  Share2,
  Trash2,
  History,
  Loader2,
} from 'lucide-react';

import { formatDateTime } from '@/utils/date';

import { AppModal } from '@/components/common';

import { schemaAPI } from '../../../services/api';
import { confirmAction } from '../../../utils/confirmAction';
import { logger } from '../../../utils/logger';

import { AttributeEditor, createEmptyAttribute, updateAttributeValue } from './AttributeEditor';

import type {
  AttributeEditorLabels,
  AttributeUpdateField,
  AttributeUpdateValue,
  EditableAttribute,
} from './AttributeEditor';
import type { TFunction } from 'i18next';

// ============================================================================
// Types
// ============================================================================

export interface EdgeType {
  id: string;
  name: string;
  description: string;
  schema: EdgeSchema;
  status: 'ENABLED' | 'DISABLED';
  source: 'user' | 'generated';
  created_at: string;
  updated_at: string;
}

type EdgeSchemaField =
  | string
  | {
      type?: string | undefined;
      description?: string | undefined;
      required?: boolean | undefined;
      [key: string]: unknown;
    };

type EdgeSchema = Record<string, EdgeSchemaField>;

interface EdgeFormData {
  name: string;
  description: string;
  schema: EdgeSchema;
}

export type Attribute = EditableAttribute;

const schemaEntryToAttribute = ([name, value]: [string, EdgeSchemaField]): Attribute => {
  if (typeof value === 'string') {
    return { name, type: value, description: '', required: false };
  }

  return {
    name,
    type: typeof value.type === 'string' ? value.type : 'String',
    description: typeof value.description === 'string' ? value.description : '',
    required: value.required === true,
  };
};

const schemaToAttributes = (schema: EdgeSchema): Attribute[] =>
  Object.entries(schema).map(schemaEntryToAttribute);

const normalizeEdgeSchemaField = (value: unknown): EdgeSchemaField => {
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    return value as EdgeSchemaField;
  }
  return { type: 'String' };
};

const toEdgeSchema = (schema: Record<string, unknown> | undefined): EdgeSchema => {
  if (!schema) return {};
  return Object.fromEntries(
    Object.entries(schema).map(([key, value]) => [key, normalizeEdgeSchemaField(value)])
  );
};

const attributesToSchema = (attributes: Attribute[]): EdgeSchema => {
  const schema: EdgeSchema = {};

  attributes.forEach((attr) => {
    if (attr.name) {
      schema[attr.name] = {
        type: attr.type,
        description: attr.description,
        required: attr.required,
      };
    }
  });

  return schema;
};

// ============================================================================
// Constants
// ============================================================================

const TEXTS = {
  title: 'Edge Types',
  subtitle: 'Define the structure of relationships in your knowledge graph',
  create: 'Create Edge Type',
  searchPlaceholder: 'Search edge types…',
  systemActive: 'System Active',

  // Master Pane
  master: {
    active: 'ACTIVE',
    noDescription: 'No description provided',
    attributesCount: '{{count}} attributes',
    empty: 'No edge types defined yet. Create your first one to get started.',
  },

  // Detail Pane
  detail: {
    selectPrompt: 'Select an edge type from the list to view its details',
    noDescription: 'No description provided',
    delete: 'Delete',
    edit: 'Edit',
    attributesTitle: 'Edge Attributes',
    addAttribute: 'Add Attribute',
    table: {
      name: 'Name',
      type: 'Type',
      description: 'Description',
      empty: 'No attributes defined for this edge type.',
    },
  },

  // Modal
  modal: {
    titleNew: 'New Edge Type',
    titleEdit: 'Edit {{name}}',
    nameLabel: 'Name',
    namePlaceholder: 'e.g. KNOWS, WORKS_FOR, LOCATED_IN',
    descLabel: 'Description',
    descPlaceholder: 'What does this relationship represent?',
    tabAttributes: 'Attributes',
    basicInfo: 'Basic Information',
    definedAttributes: 'Defined Attributes',
    addAttribute: 'Add Attribute',
    attributeTitle: 'Attribute #{{index}}',
    deleteField: 'Remove',
    attrNameLabel: 'Attribute Name',
    attrNamePlaceholder: 'e.g. since, strength, context',
    dataTypeLabel: 'Data Type',
    docstringLabel: 'Documentation',
    docstringPlaceholder: 'Describe what this attribute represents',
    lastSaved: 'Last saved: {{time}}',
    neverSaved: 'Never',
    discard: 'Discard',
    save: 'Save',
  },

  // Common
  deleteConfirm: 'Are you sure you want to delete this edge type?',
  loading: 'Loading…',
};

type TranslationValues = Record<string, number | string>;

function edgeText(
  t: TFunction,
  key: string,
  defaultValue: string,
  values: TranslationValues = {}
): string {
  return t(`project.schema.edgeTypeList.${key}`, { defaultValue, ...values });
}

// ============================================================================
// Marker Symbols
// ============================================================================

const HeaderMarker = Symbol('EdgeTypeList.Header');
const ToolbarMarker = Symbol('EdgeTypeList.Toolbar');
const MasterPaneMarker = Symbol('EdgeTypeList.MasterPane');
const DetailPaneMarker = Symbol('EdgeTypeList.DetailPane');
const StatusBadgeMarker = Symbol('EdgeTypeList.StatusBadge');
const SourceBadgeMarker = Symbol('EdgeTypeList.SourceBadge');
const EmptyMarker = Symbol('EdgeTypeList.Empty');
const LoadingMarker = Symbol('EdgeTypeList.Loading');
const ModalMarker = Symbol('EdgeTypeList.Modal');

// ============================================================================
// Context
// ============================================================================

interface EdgeTypeListState {
  edges: EdgeType[];
  loading: boolean;
  loadError: string | null;
  search: string;
  selectedEdgeId: string | null;
  isModalOpen: boolean;
  editingEdge: EdgeType | null;
  formData: EdgeFormData;
  attributes: Attribute[];
  isSaving: boolean;
}

interface EdgeTypeListActions {
  setSearch: (search: string) => void;
  setSelectedEdgeId: (id: string | null) => void;
  handleOpenModal: (edge: EdgeType | null) => void;
  handleCloseModal: () => void;
  handleSave: () => void;
  handleDelete: (id: string) => void;
  setFormData: (data: EdgeFormData) => void;
  setAttributes: (attrs: Attribute[]) => void;
  addAttribute: () => void;
  updateAttribute: (
    index: number,
    field: AttributeUpdateField,
    value: AttributeUpdateValue
  ) => void;
  removeAttribute: (index: number) => void;
}

interface EdgeTypeListContextType {
  state: EdgeTypeListState;
  actions: EdgeTypeListActions;
}

const EdgeTypeListContext = React.createContext<EdgeTypeListContextType | null>(null);

const useEdgeTypeListContext = (): EdgeTypeListContextType => {
  const context = useContext(EdgeTypeListContext);
  if (!context) {
    throw new Error('EdgeTypeList sub-components must be used within EdgeTypeList');
  }
  return context;
};

// Optional hook for testing - returns null if not in context
const useEdgeTypeListContextOptional = (): EdgeTypeListContextType | null => {
  return useContext(EdgeTypeListContext);
};

// ============================================================================
// Main Component
// ============================================================================

interface EdgeTypeListProps {
  className?: string | undefined;
}

const EdgeTypeListInternal: React.FC<EdgeTypeListProps> = ({ className = '' }) => {
  const { t } = useTranslation();
  const { projectId } = useParams<{ projectId: string }>();

  // State
  const [edges, setEdges] = useState<EdgeType[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingEdge, setEditingEdge] = useState<EdgeType | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  // Form state
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    schema: {},
  });
  const [attributes, setAttributes] = useState<Attribute[]>([]);

  // Load data
  const loadData = useCallback(async () => {
    if (!projectId) return;
    setLoadError(null);
    try {
      const data = await schemaAPI.listEdgeTypes(projectId);
      // Convert SchemaEdgeType to EdgeType
      const loadedAt = new Date().toISOString();
      const edgeTypes: EdgeType[] = data.map((item) => ({
        id: item.id,
        name: item.name,
        description: item.description || '',
        schema: toEdgeSchema(item.schema ?? item.properties),
        status: item.status === 'DISABLED' ? 'DISABLED' : 'ENABLED',
        source: item.source === 'generated' ? 'generated' : 'user',
        created_at: item.created_at ?? loadedAt,
        updated_at: item.updated_at ?? item.created_at ?? loadedAt,
      }));
      setEdges(edgeTypes);
      if (edgeTypes.length > 0 && !selectedEdgeId) {
        setSelectedEdgeId(edgeTypes[0]?.id ?? null);
      }
    } catch (error) {
      logger.error('[EdgeTypeList] Failed to load edge types:', error);
      setLoadError(edgeText(t, 'loadError', 'Failed to load edge types.'));
    } finally {
      setLoading(false);
    }
  }, [projectId, selectedEdgeId, t]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Handlers
  const handleOpenModal = useCallback((edge: EdgeType | null) => {
    if (edge) {
      setEditingEdge(edge);
      setFormData({
        name: edge.name,
        description: edge.description,
        schema: edge.schema,
      });
      setAttributes(schemaToAttributes(edge.schema));
    } else {
      setEditingEdge(null);
      setFormData({ name: '', description: '', schema: {} });
      setAttributes([]);
    }
    setIsModalOpen(true);
  }, []);

  const handleCloseModal = useCallback(() => {
    setIsModalOpen(false);
    setEditingEdge(null);
  }, []);

  const handleSave = useCallback(async () => {
    if (!projectId || isSaving) return;

    const payload = {
      ...formData,
      schema: attributesToSchema(attributes),
    };

    setIsSaving(true);
    try {
      if (editingEdge) {
        await schemaAPI.updateEdgeType(projectId, editingEdge.id, payload);
      } else {
        await schemaAPI.createEdgeType(projectId, payload);
      }
      setIsModalOpen(false);
      setEditingEdge(null);
      await loadData();
    } catch (error) {
      logger.error('[EdgeTypeList] Failed to save edge type:', error);
      void message.error(edgeText(t, 'saveError', 'Failed to save edge type'));
    } finally {
      setIsSaving(false);
    }
  }, [projectId, editingEdge, formData, attributes, isSaving, loadData, t]);

  const handleDelete = useCallback(
    async (id: string) => {
      if (
        !(await confirmAction({
          title: edgeText(t, 'deleteConfirm', TEXTS.deleteConfirm),
          danger: true,
        }))
      )
        return;
      if (!projectId) return;
      try {
        await schemaAPI.deleteEdgeType(projectId, id);
        if (selectedEdgeId === id) {
          setSelectedEdgeId(null);
        }
        await loadData();
      } catch (error) {
        logger.error('[EdgeTypeList] Failed to delete:', error);
        void message.error(edgeText(t, 'deleteError', 'Failed to delete edge type'));
      }
    },
    [projectId, selectedEdgeId, loadData, t]
  );

  const addAttribute = useCallback(() => {
    setAttributes([...attributes, createEmptyAttribute()]);
  }, [attributes]);

  const updateAttribute = useCallback(
    (index: number, field: AttributeUpdateField, value: AttributeUpdateValue) => {
      const newAttrs = [...attributes];
      const existing = newAttrs[index];
      if (existing) {
        newAttrs[index] = updateAttributeValue(existing, field, value);
      }
      setAttributes(newAttrs);
    },
    [attributes]
  );

  const removeAttribute = useCallback(
    (index: number) => {
      setAttributes(attributes.filter((_, i) => i !== index));
    },
    [attributes]
  );

  // Filter edges
  const filteredEdges = useMemo(() => {
    if (!search) return edges;
    const lowerSearch = search.toLowerCase();
    return edges.filter(
      (e) =>
        e.name.toLowerCase().includes(lowerSearch) ||
        e.description.toLowerCase().includes(lowerSearch)
    );
  }, [edges, search]);

  // Context state
  const state: EdgeTypeListState = {
    edges,
    loading,
    loadError,
    search,
    selectedEdgeId,
    isModalOpen,
    editingEdge,
    formData,
    attributes,
    isSaving,
  };

  // Context actions
  const actions: EdgeTypeListActions = {
    setSearch,
    setSelectedEdgeId,
    handleOpenModal,
    handleCloseModal,
    handleSave: () => {
      void handleSave();
    },
    handleDelete: (id) => {
      void handleDelete(id);
    },
    setFormData,
    setAttributes,
    addAttribute,
    updateAttribute,
    removeAttribute,
  };

  if (loading) {
    return <EdgeTypeList.Loading />;
  }

  return (
    <EdgeTypeListContext.Provider value={{ state, actions }}>
      <div
        className={
          className ||
          'flex flex-col h-full bg-slate-50 dark:bg-background-dark text-slate-900 dark:text-white overflow-hidden'
        }
      >
        <EdgeTypeList.Header />
        <div className="flex-1 overflow-y-auto bg-slate-50 dark:bg-background-dark p-4 sm:p-6 lg:p-8">
          {loadError ? (
            <div
              role="alert"
              className="mx-auto flex max-w-[1600px] flex-col items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-center dark:border-red-500/30 dark:bg-red-500/10"
            >
              <p className="text-sm text-red-600 dark:text-red-400">{loadError}</p>
              <button
                type="button"
                onClick={() => {
                  void loadData();
                }}
                className="inline-flex h-9 items-center rounded-lg bg-slate-950 px-4 text-sm font-medium text-slate-50 transition-colors hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950/20 dark:bg-slate-50 dark:text-slate-950 dark:hover:bg-slate-200 dark:focus-visible:ring-slate-50/20"
              >
                {edgeText(t, 'retry', 'Retry')}
              </button>
            </div>
          ) : (
            <div className="mx-auto flex min-h-[600px] max-w-[1600px] flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm dark:border-border-dark dark:bg-surface-dark">
              <EdgeTypeList.Toolbar />
              <div className="flex flex-1 flex-col overflow-visible lg:h-[600px] lg:flex-row lg:overflow-hidden">
                <EdgeTypeList.MasterPane
                  edges={filteredEdges}
                  onSelect={actions.setSelectedEdgeId}
                />
                <EdgeTypeList.DetailPane
                  selectedEdgeId={selectedEdgeId}
                  edges={filteredEdges}
                  onEdit={actions.handleOpenModal}
                  onDelete={actions.handleDelete}
                />
              </div>
            </div>
          )}
        </div>
        {isModalOpen && (
          <EdgeTypeList.Modal
            isOpen={isModalOpen}
            onClose={actions.handleCloseModal}
            onSave={actions.handleSave}
            editingEdge={editingEdge}
          />
        )}
      </div>
    </EdgeTypeListContext.Provider>
  );
};

EdgeTypeListInternal.displayName = 'EdgeTypeList';

// ============================================================================
// Header Sub-Component
// ============================================================================

interface HeaderProps {
  onCreate?: (() => void) | undefined;
}

const HeaderInternal: React.FC<HeaderProps> = () => {
  const { t } = useTranslation();

  return (
    <div className="w-full flex-none border-b border-slate-200 bg-white px-4 pb-4 pt-6 dark:border-border-dark/50 dark:bg-background-dark sm:px-6 lg:px-8">
      <div className="max-w-[1600px] mx-auto flex flex-col gap-4">
        <div className="flex flex-wrap justify-between items-end gap-4">
          <div className="flex flex-col gap-2 max-w-2xl">
            <h1 className="text-slate-900 dark:text-white text-3xl font-black leading-tight tracking-tight">
              {edgeText(t, 'title', TEXTS.title)}
            </h1>
            <p className="text-slate-500 dark:text-text-muted text-base font-normal">
              {edgeText(t, 'subtitle', TEXTS.subtitle)}
            </p>
          </div>
          <div className="flex gap-2">
            <span className="px-3 py-1 rounded-full bg-green-50 dark:bg-green-500/10 text-green-600 dark:text-green-400 text-xs font-medium border border-green-200 dark:border-green-500/20">
              {edgeText(t, 'systemActive', TEXTS.systemActive)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

HeaderInternal.displayName = 'EdgeTypeList.Header';

// ============================================================================
// Toolbar Sub-Component
// ============================================================================

interface ToolbarProps {
  search?: string | undefined;
  onSearchChange?: ((value: string) => void) | undefined;
  onCreate?: (() => void) | undefined;
}

const ToolbarInternal: React.FC<ToolbarProps> = (props) => {
  const { t } = useTranslation();
  const contextFromHook = useEdgeTypeListContextOptional();
  const hasProps = props.onSearchChange !== undefined;
  const context = hasProps ? null : contextFromHook;
  const state = context?.state;
  const actions = context?.actions;

  const search = props.search ?? state?.search ?? '';
  const setSearch = props.onSearchChange ?? actions?.setSearch;
  const handleCreate = props.onCreate ?? actions?.handleOpenModal;
  const edges = state?.edges;

  const handleDownload = useCallback(() => {
    const payload = JSON.stringify(edges ?? [], null, 2);
    const blob = new Blob([payload], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'edge-types-schema.json';
    anchor.click();
    URL.revokeObjectURL(url);
  }, [edges]);

  return (
    <div className="flex flex-col gap-4 border-b border-slate-200 bg-slate-50 px-4 py-4 dark:border-border-dark dark:bg-background-dark sm:flex-row sm:items-center sm:justify-between sm:px-6">
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
        <div className="relative group w-full sm:w-auto">
          <div className="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none">
            <Search className="text-slate-400 dark:text-text-muted w-5 h-5" />
          </div>
          <input
            className="block w-full rounded-lg border border-slate-200 bg-white p-2.5 pl-10 text-sm text-slate-900 outline-none transition-[color,background-color,border-color,box-shadow,opacity,transform] placeholder-slate-400 focus:border-blue-600 focus:ring-blue-600 dark:border-border-dark dark:bg-background-dark dark:text-white dark:placeholder-gray-500 dark:focus:border-primary dark:focus:ring-primary sm:w-64 sm:focus:w-80"
            placeholder={edgeText(t, 'searchPlaceholder', TEXTS.searchPlaceholder)}
            aria-label={edgeText(t, 'searchPlaceholder', TEXTS.searchPlaceholder)}
            type="text"
            value={search}
            onChange={(e) => setSearch?.(e.target.value)}
          />
        </div>
        <div className="mx-2 hidden h-6 w-px bg-slate-200 dark:bg-border-dark sm:block"></div>
        <button
          className="p-2 text-slate-500 dark:text-text-muted hover:text-slate-900 dark:hover:text-white hover:bg-slate-200 dark:hover:bg-white/5 rounded-lg transition-colors"
          title={edgeText(t, 'downloadSchema', 'Download Schema')}
          aria-label={edgeText(t, 'downloadSchema', 'Download Schema')}
          onClick={handleDownload}
          type="button"
        >
          <Download className="w-5 h-5" />
        </button>
      </div>
      <button
        type="button"
        onClick={() => handleCreate?.(null)}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-bold text-white shadow-lg shadow-blue-900/20 transition-[color,background-color,border-color,box-shadow,opacity] hover:bg-blue-700 dark:bg-primary sm:w-auto"
      >
        <Plus className="w-5 h-5" />
        <span>{edgeText(t, 'createButton', TEXTS.create)}</span>
      </button>
    </div>
  );
};

ToolbarInternal.displayName = 'EdgeTypeList.Toolbar';

// ============================================================================
// StatusBadge Sub-Component
// ============================================================================

interface StatusBadgeProps {
  status: string;
}

const StatusBadgeInternal: React.FC<StatusBadgeProps> = React.memo(({ status }) => {
  const { t } = useTranslation();
  const normalizedStatus = status || 'ENABLED';

  return (
    <span
      className={`px-2 py-0.5 rounded-full text-xs font-bold uppercase tracking-wide border ${
        normalizedStatus === 'ENABLED'
          ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20'
          : 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-700'
      }`}
    >
      {edgeText(t, `status.${normalizedStatus.toLowerCase()}`, normalizedStatus)}
    </span>
  );
});

StatusBadgeInternal.displayName = 'EdgeTypeList.StatusBadge';

// ============================================================================
// SourceBadge Sub-Component
// ============================================================================

interface SourceBadgeProps {
  source: string;
}

const SourceBadgeInternal: React.FC<SourceBadgeProps> = React.memo(({ source }) => {
  const { t } = useTranslation();
  const sourceKey = source === 'generated' ? 'generated' : 'user';

  return (
    <span
      className={`px-2 py-0.5 rounded-full text-2xs uppercase tracking-wider font-bold ${
        sourceKey === 'generated'
          ? 'bg-purple-50 dark:bg-purple-500/10 text-purple-600 dark:text-purple-400 border border-purple-200 dark:border-purple-500/20'
          : 'bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-500/20'
      }`}
    >
      {edgeText(t, `source.${sourceKey}`, sourceKey === 'generated' ? 'AUTO' : 'USER')}
    </span>
  );
});

SourceBadgeInternal.displayName = 'EdgeTypeList.SourceBadge';

// ============================================================================
// MasterPane Sub-Component
// ============================================================================

interface MasterPaneProps {
  edges: EdgeType[];
  selectedEdgeId?: string | null | undefined;
  onSelect: (id: string | null) => void;
}

const MasterPaneInternal: React.FC<MasterPaneProps> = React.memo(
  ({ edges, selectedEdgeId, onSelect }) => {
    const { t } = useTranslation();

    if (edges.length === 0) {
      return <EdgeTypeList.Empty />;
    }

    return (
      <div
        className="max-h-72 w-full overflow-y-auto border-b border-slate-200 bg-slate-50 dark:border-border-dark dark:bg-background-dark lg:max-h-none lg:w-1/3 lg:border-b-0 lg:border-r"
        role="listbox"
        aria-label={edgeText(t, 'title', TEXTS.title)}
      >
        {edges.map((edge) => (
          <button
            type="button"
            key={edge.id}
            role="option"
            aria-selected={selectedEdgeId === edge.id}
            onClick={() => {
              onSelect(edge.id);
            }}
            className={`block w-full border-b border-slate-200 p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-600/40 dark:border-border-dark dark:focus-visible:ring-blue-400/40 ${
              selectedEdgeId === edge.id
                ? 'bg-blue-50 dark:bg-primary/10 hover:bg-blue-100 dark:hover:bg-primary/20'
                : 'hover:bg-slate-100 dark:hover:bg-white/5'
            }`}
          >
            <div className="flex justify-between items-start mb-1">
              <div className="flex items-center gap-2">
                <h3 className="text-slate-900 dark:text-white font-semibold text-sm">
                  {edge.name}
                </h3>
                {edge.source === 'generated' && <EdgeTypeList.SourceBadge source={edge.source} />}
              </div>
              {selectedEdgeId === edge.id && (
                <span className="text-2xs uppercase tracking-wider text-blue-600 dark:text-primary font-bold bg-blue-100 dark:bg-primary/20 px-1.5 py-0.5 rounded">
                  {edgeText(t, 'masterActive', TEXTS.master.active)}
                </span>
              )}
            </div>
            <p className="text-slate-500 dark:text-text-muted text-xs mb-3 line-clamp-2">
              {edge.description || edgeText(t, 'masterNoDescription', TEXTS.master.noDescription)}
            </p>
            <div className="flex items-center gap-4 text-xs text-slate-500 dark:text-text-muted">
              <div className="flex items-center gap-1">
                <Code className="w-3.5 h-3.5" aria-hidden="true" />
                <span>
                  {edgeText(t, 'masterAttributesCount', TEXTS.master.attributesCount, {
                    count: Object.keys(edge.schema).length,
                  })}
                </span>
              </div>
            </div>
          </button>
        ))}
      </div>
    );
  }
);

MasterPaneInternal.displayName = 'EdgeTypeList.MasterPane';

// ============================================================================
// DetailPane Sub-Component
// ============================================================================

interface DetailPaneProps {
  selectedEdgeId: string | null;
  edges: EdgeType[];
  onEdit: (edge: EdgeType) => void;
  onDelete: (id: string) => void;
}

const DetailPaneInternal: React.FC<DetailPaneProps> = React.memo(
  ({ selectedEdgeId, edges, onEdit, onDelete }) => {
    const { t } = useTranslation();
    const selectedEdge = edges.find((e) => e.id === selectedEdgeId);

    if (!selectedEdge) {
      return (
        <div className="min-w-0 flex-1 overflow-y-auto bg-white p-6 dark:bg-surface-dark sm:p-8">
          <div className="flex min-h-64 flex-col items-center justify-center text-slate-400 dark:text-text-muted lg:h-full">
            <Share2 className="w-12 h-12 mb-4 opacity-50" />
            <p>{edgeText(t, 'detailSelectPrompt', TEXTS.detail.selectPrompt)}</p>
          </div>
        </div>
      );
    }

    return (
      <div className="min-w-0 flex-1 overflow-y-auto bg-white p-6 dark:bg-surface-dark sm:p-8">
        {/* Detail Header */}
        <div className="flex justify-between items-start mb-8 pb-6 border-b border-slate-200 dark:border-border-dark">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <h2 className="text-2xl font-bold text-slate-900 dark:text-white">
                {selectedEdge.name}
              </h2>
              <div title={`ID: ${selectedEdge.id}`}>
                <Info className="text-slate-400 dark:text-text-muted cursor-help w-5 h-5" />
              </div>
              <div className="flex gap-2 ml-2">
                <EdgeTypeList.StatusBadge status={selectedEdge.status} />
                <EdgeTypeList.SourceBadge source={selectedEdge.source} />
              </div>
            </div>
            <p className="text-slate-500 dark:text-text-muted text-sm max-w-xl">
              {selectedEdge.description ||
                edgeText(t, 'detailNoDescription', TEXTS.detail.noDescription)}
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => {
                onDelete(selectedEdge.id);
              }}
              className="px-3 py-1.5 text-sm font-medium text-slate-500 dark:text-text-muted hover:text-red-600 dark:hover:text-red-400 border border-slate-200 dark:border-border-dark rounded bg-white dark:bg-background-dark hover:bg-slate-50 dark:hover:bg-surface-dark-alt transition-colors flex items-center gap-2"
            >
              <Trash2 className="w-4 h-4" />
              {edgeText(t, 'detailDelete', TEXTS.detail.delete)}
            </button>
            <button
              type="button"
              onClick={() => {
                onEdit(selectedEdge);
              }}
              className="px-3 py-1.5 text-sm font-medium text-white bg-blue-600 dark:bg-primary hover:bg-blue-700 rounded transition-colors flex items-center gap-2"
            >
              <Pencil className="w-4 h-4" />
              {edgeText(t, 'detailEdit', TEXTS.detail.edit)}
            </button>
          </div>
        </div>

        {/* Attributes Section */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white flex items-center gap-2">
              <Code className="text-blue-600 dark:text-primary w-5 h-5" />
              {edgeText(t, 'detailAttributesTitle', TEXTS.detail.attributesTitle)}
            </h3>
            <span className="text-xs text-slate-500 dark:text-text-muted font-mono bg-slate-100 dark:bg-background-dark px-2 py-1 rounded border border-slate-200 dark:border-border-dark">
              class {selectedEdge.name}(Edge)
            </span>
          </div>
          <div className="border border-slate-200 dark:border-border-dark rounded-lg overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 dark:bg-background-dark text-slate-500 dark:text-text-muted border-b border-slate-200 dark:border-border-dark">
                <tr>
                  <th className="px-4 py-3 font-medium">
                    {edgeText(t, 'detailTableName', TEXTS.detail.table.name)}
                  </th>
                  <th className="px-4 py-3 font-medium">
                    {edgeText(t, 'detailTableType', TEXTS.detail.table.type)}
                  </th>
                  <th className="px-4 py-3 font-medium">
                    {edgeText(t, 'detailTableDescription', TEXTS.detail.table.description)}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-border-dark bg-white dark:bg-background-dark/50">
                {Object.entries(selectedEdge.schema).map(([key, val]) => (
                  <tr
                    key={key}
                    className="group hover:bg-slate-50 dark:hover:bg-white/5 transition-colors"
                  >
                    <td className="px-4 py-3 text-slate-900 dark:text-white font-mono text-xs">
                      {key}
                    </td>
                    <td className="px-4 py-3 text-purple-600 dark:text-purple-400 font-mono text-xs">
                      {typeof val === 'string' ? val : (val.type ?? 'String')}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-text-muted text-xs">
                      {typeof val === 'string' ? '' : (val.description ?? '')}
                    </td>
                  </tr>
                ))}
                {Object.keys(selectedEdge.schema).length === 0 && (
                  <tr>
                    <td
                      colSpan={3}
                      className="px-4 py-8 text-center text-slate-500 dark:text-text-muted"
                    >
                      {edgeText(t, 'detailTableEmpty', TEXTS.detail.table.empty)}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            <div className="bg-slate-50 dark:bg-background-dark px-4 py-2 border-t border-slate-200 dark:border-border-dark">
              <button
                type="button"
                onClick={() => {
                  onEdit(selectedEdge);
                }}
                className="text-xs text-blue-600 dark:text-primary font-bold flex items-center gap-1 hover:text-blue-800 dark:hover:text-white transition-colors"
              >
                <Plus className="w-4 h-4" />
                {edgeText(t, 'detailAddAttribute', TEXTS.detail.addAttribute)}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }
);

DetailPaneInternal.displayName = 'EdgeTypeList.DetailPane';

// ============================================================================
// Empty Sub-Component
// ============================================================================

const EmptyInternal: React.FC = () => {
  const { t } = useTranslation();

  return (
    <div className="w-full border-b border-slate-200 p-6 text-center text-sm text-slate-500 dark:border-border-dark dark:text-text-muted lg:w-1/3 lg:border-b-0 lg:border-r">
      {edgeText(t, 'masterEmpty', TEXTS.master.empty)}
    </div>
  );
};

EmptyInternal.displayName = 'EdgeTypeList.Empty';

// ============================================================================
// Loading Sub-Component
// ============================================================================

const LoadingInternal: React.FC = () => {
  const { t } = useTranslation();

  return (
    <div className="p-8 text-center text-slate-500 dark:text-gray-500">
      {edgeText(t, 'loading', TEXTS.loading)}
    </div>
  );
};

LoadingInternal.displayName = 'EdgeTypeList.Loading';

// ============================================================================
// Modal Sub-Component
// ============================================================================

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: () => void;
  editingEdge: EdgeType | null;
}

const ModalInternal: React.FC<ModalProps> = React.memo(
  ({ isOpen, onClose, onSave, editingEdge }) => {
    const { t } = useTranslation();
    const context = useEdgeTypeListContextOptional();
    const [localFormData, setLocalFormData] = useState<EdgeFormData>({
      name: editingEdge?.name ?? '',
      description: editingEdge?.description ?? '',
      schema: editingEdge?.schema ?? {},
    });
    const [localAttributes, setLocalAttributes] = useState<Attribute[]>(
      editingEdge ? schemaToAttributes(editingEdge.schema) : []
    );

    const formData = context?.state.formData ?? localFormData;
    const attributes = context?.state.attributes ?? localAttributes;
    const setFormData = context?.actions.setFormData ?? setLocalFormData;
    const setAttributes = context?.actions.setAttributes ?? setLocalAttributes;

    // Reset form when editingEntity changes
    React.useEffect(() => {
      if (editingEdge) {
        setFormData({
          name: editingEdge.name,
          description: editingEdge.description,
          schema: editingEdge.schema,
        });
        setAttributes(schemaToAttributes(editingEdge.schema));
      } else {
        setFormData({ name: '', description: '', schema: {} });
        setAttributes([]);
      }
    }, [editingEdge, setAttributes, setFormData]);

    const addAttribute = useCallback(() => {
      setAttributes([...attributes, createEmptyAttribute()]);
    }, [attributes, setAttributes]);

    const updateAttribute = useCallback(
      (index: number, field: AttributeUpdateField, value: AttributeUpdateValue) => {
        const newAttrs = [...attributes];
        const existing = newAttrs[index];
        if (existing) {
          newAttrs[index] = updateAttributeValue(existing, field, value);
        }
        setAttributes(newAttrs);
      },
      [attributes, setAttributes]
    );

    const removeAttribute = useCallback(
      (index: number) => {
        setAttributes(attributes.filter((_, i) => i !== index));
      },
      [attributes, setAttributes]
    );

    const isSaving = context?.state.isSaving ?? false;

    const attributeEditorLabels: AttributeEditorLabels = {
      definedAttributes: edgeText(t, 'modalDefinedAttributes', TEXTS.modal.definedAttributes),
      addAttribute: edgeText(t, 'modalAddAttribute', TEXTS.modal.addAttribute),
      attributeTitle: (index) =>
        edgeText(t, 'modalAttributeTitle', TEXTS.modal.attributeTitle, { index }),
      removeAttribute: edgeText(t, 'modalDeleteField', TEXTS.modal.deleteField),
      nameLabel: edgeText(t, 'modalAttrNameLabel', TEXTS.modal.attrNameLabel),
      namePlaceholder: edgeText(t, 'modalAttrNamePlaceholder', TEXTS.modal.attrNamePlaceholder),
      dataTypeLabel: edgeText(t, 'modalDataTypeLabel', TEXTS.modal.dataTypeLabel),
      requiredLabel: edgeText(t, 'modalRequired', 'Required'),
      docstringLabel: edgeText(t, 'modalDocstringLabel', TEXTS.modal.docstringLabel),
      docstringPlaceholder: edgeText(
        t,
        'modalDocstringPlaceholder',
        TEXTS.modal.docstringPlaceholder
      ),
    };

    if (!isOpen) return null;

    return (
      <AppModal
        open={isOpen}
        onClose={onClose}
        position="side"
        size="xl"
        ariaLabel={edgeText(t, 'modal.close', 'Close relationship type editor')}
        title={
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center h-10 w-10 rounded-lg bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-500/20">
              <Share2 className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-900 dark:text-white leading-none">
                {editingEdge
                  ? edgeText(t, 'modalTitleEdit', TEXTS.modal.titleEdit, {
                      name: editingEdge.name,
                    })
                  : edgeText(t, 'modalTitleNew', TEXTS.modal.titleNew)}
              </h3>
              <p className="text-xs text-slate-500 dark:text-text-muted mt-1 font-mono">
                {editingEdge?.id || edgeText(t, 'newId', 'New ID')}
              </p>
            </div>
          </div>
        }
        footer={
          <>
            <div className="mr-auto text-xs text-slate-500 dark:text-text-muted flex items-center gap-1">
              <History className="w-4 h-4" />
              <span>
                {edgeText(t, 'modalLastSaved', TEXTS.modal.lastSaved, {
                  time: editingEdge?.updated_at
                    ? formatDateTime(editingEdge.updated_at)
                    : edgeText(t, 'modalNeverSaved', TEXTS.modal.neverSaved),
                })}
              </span>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-slate-500 dark:text-text-muted hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-border-dark rounded-lg hover:bg-slate-100 dark:hover:bg-border-dark transition-colors"
            >
              {edgeText(t, 'modalDiscard', TEXTS.modal.discard)}
            </button>
            <button
              type="button"
              onClick={onSave}
              disabled={isSaving}
              className="inline-flex items-center gap-2 px-5 py-2 text-sm font-bold text-white bg-blue-600 dark:bg-primary rounded-lg hover:bg-blue-700 dark:hover:bg-primary-light shadow-lg shadow-blue-900/20 transition-[color,background-color,border-color,box-shadow,opacity] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSaving && (
                <Loader2
                  className="w-4 h-4 animate-spin motion-reduce:animate-none"
                  aria-hidden="true"
                />
              )}
              {isSaving
                ? edgeText(t, 'modalSaving', 'Saving…')
                : edgeText(t, 'modalSave', TEXTS.modal.save)}
            </button>
          </>
        }
      >
        <div className="flex-1 overflow-y-auto">
            <div className="flex border-b border-slate-200 dark:border-border-dark sticky top-0 bg-white dark:bg-background-dark z-10 px-6 pt-2">
              <h4 className="px-4 py-3 text-sm font-bold text-blue-600 dark:text-blue-400 border-b-2 border-blue-600 dark:border-blue-400 bg-blue-50 dark:bg-blue-500/5">
                {edgeText(t, 'modalTabAttributes', TEXTS.modal.tabAttributes)}
              </h4>
            </div>
            <div className="p-6 flex flex-col gap-8">
              {/* Basic Info */}
              <div className="flex flex-col gap-4">
                <h4 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
                  {edgeText(t, 'modalBasicInfo', TEXTS.modal.basicInfo)}
                </h4>
                <div className="grid grid-cols-1 gap-4">
                  <div>
                    <label
                      htmlFor="edge-type-name"
                      className="text-2xs uppercase text-slate-500 dark:text-text-muted font-bold mb-1.5 block"
                    >
                      {edgeText(t, 'modalNameLabel', TEXTS.modal.nameLabel)}
                    </label>
                    <input
                      id="edge-type-name"
                      className="w-full bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-border-dark rounded-lg text-sm text-slate-900 dark:text-white px-3 py-2 font-mono focus:border-blue-600 dark:focus:border-primary focus:ring-1 focus:ring-blue-600 dark:focus:ring-primary outline-none transition-colors"
                      type="text"
                      spellCheck={false}
                      value={formData.name}
                      onChange={(e) => {
                        setFormData({ ...formData, name: e.target.value });
                      }}
                      placeholder={edgeText(t, 'modalNamePlaceholder', TEXTS.modal.namePlaceholder)}
                      disabled={!!editingEdge}
                    />
                  </div>
                  <div>
                    <label className="text-2xs uppercase text-slate-500 dark:text-text-muted font-bold mb-1.5 block">
                      {edgeText(t, 'modalDescLabel', TEXTS.modal.descLabel)}
                    </label>
                    <input
                      className="w-full bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-border-dark rounded-lg text-sm text-slate-900 dark:text-white px-3 py-2 focus:border-blue-600 dark:focus:border-primary focus:ring-1 focus:ring-blue-600 dark:focus:ring-primary outline-none transition-colors"
                      type="text"
                      value={formData.description}
                      onChange={(e) => {
                        setFormData({ ...formData, description: e.target.value });
                      }}
                      placeholder={edgeText(t, 'modalDescPlaceholder', TEXTS.modal.descPlaceholder)}
                    />
                  </div>
                </div>
              </div>

              {/* Attributes */}
              <AttributeEditor
                attributes={attributes}
                onAdd={addAttribute}
                onUpdate={updateAttribute}
                onRemove={removeAttribute}
                labels={attributeEditorLabels}
              />
            </div>
          </div>
      </AppModal>
    );
  }
);

ModalInternal.displayName = 'EdgeTypeList.Modal';

// ============================================================================
// Attach Sub-Components to Main Component
// ============================================================================

const attachMarker = <P extends object>(component: React.FC<P>, marker: symbol) => {
  const marked = component as React.FC<P> & Record<symbol, true>;
  marked[marker] = true;
  return marked;
};

// Export the compound component
export const EdgeTypeList = Object.assign(EdgeTypeListInternal, {
  Header: attachMarker(HeaderInternal, HeaderMarker),
  Toolbar: attachMarker(ToolbarInternal, ToolbarMarker),
  MasterPane: attachMarker(MasterPaneInternal, MasterPaneMarker),
  DetailPane: attachMarker(DetailPaneInternal, DetailPaneMarker),
  StatusBadge: attachMarker(StatusBadgeInternal, StatusBadgeMarker),
  SourceBadge: attachMarker(SourceBadgeInternal, SourceBadgeMarker),
  Empty: attachMarker(EmptyInternal, EmptyMarker),
  Loading: attachMarker(LoadingInternal, LoadingMarker),
  Modal: attachMarker(ModalInternal, ModalMarker),
  useContext: useEdgeTypeListContext,
});

export default EdgeTypeList;
