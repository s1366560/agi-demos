/**
 * EntityTypeList Compound Component
 *
 * A compound component pattern for managing Entity Types with modular sub-components.
 *
 * @example
 * ```tsx
 * import { EntityTypeList } from './EntityTypeList';
 *
 * <EntityTypeList />
 * ```
 */

import React, { useCallback, useEffect, useRef, useState, useMemo, useContext } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { message } from 'antd';
import {
  Plus,
  Search,
  User,
  FileEdit,
  Info,
  History,
  Trash2,
  GripVertical,
  Loader2,
} from 'lucide-react';

import { formatDateOnly, formatDateTime } from '@/utils/date';

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

export interface EntityType {
  id: string;
  name: string;
  description: string;
  schema: EntitySchema;
  status: 'ENABLED' | 'DISABLED';
  source: 'user' | 'generated';
  created_at: string;
  updated_at: string;
}

interface EntitySchemaObject {
  type?: string | undefined;
  description?: string | undefined;
  required?: boolean | undefined;
  ge?: number | undefined;
  le?: number | undefined;
  min_len?: number | undefined;
  max_len?: number | undefined;
  regex?: string | undefined;
  [key: string]: unknown;
}

type EntitySchemaValue = string | EntitySchemaObject;
type EntitySchema = Record<string, EntitySchemaValue>;
type EntityTypeFormData = {
  name: string;
  description: string;
  schema: EntitySchema;
};

export type Attribute = EditableAttribute;

// ============================================================================
// Constants
// ============================================================================

const TEXTS = {
  title: 'Entity Types',
  subtitle: 'Define the structure of entities in your knowledge graph',
  create: 'Create Entity Type',
  searchPlaceholder: 'Search entity types…',

  // Table
  table: {
    entityType: 'Entity Type',
    internalId: 'Internal ID',
    schemaDefinition: 'Schema Definition',
    status: 'Status',
    source: 'Source',
    lastModified: 'Last Modified',
    actions: 'Actions',
    moreAttributes: '+{{count}} more',
    noAttributes: 'No attributes',
    empty: 'No entity types defined yet. Create your first one to get started.',
  },

  // Modal
  modal: {
    titleNew: 'New Entity Type',
    titleEdit: 'Edit {{name}}',
    basicInfo: 'Basic Information',
    nameLabel: 'Name',
    namePlaceholder: 'e.g. Person, Organization, Location',
    descLabel: 'Description',
    descPlaceholder: 'What does this entity type represent?',
    infoTitle: 'Attributes define the structure of your entity data.',
    infoDesc: 'Each attribute has a name, data type, and optional validation rules.',
    definedAttributes: 'Defined Attributes',
    addAttribute: 'Add Attribute',
    attributeTitle: 'Attribute #{{index}}',
    deleteField: 'Remove',
    attrNameLabel: 'Attribute Name',
    attrNamePlaceholder: 'e.g. email, phone, age',
    dataTypeLabel: 'Data Type',
    docstringLabel: 'Documentation',
    docstringPlaceholder: 'Describe what this attribute represents',
    lastSaved: 'Last saved: {{time}}',
    neverSaved: 'Never',
    discard: 'Discard',
    save: 'Save',
  },

  // Common
  edit: 'Edit',
  delete: 'Delete',
  deleteConfirm: 'Are you sure you want to delete this entity type?',
  loading: 'Loading…',

  // Tabs
  generalSettings: 'General Settings',
  attributesSchema: 'Attributes & Schema',
  relationships: 'Relationships',
  relationshipsComingSoon:
    'Define how this entity type connects to others. This feature is coming in the next update.',
  relationshipMapping: 'Relationship Mapping',

  // Validation
  validationRules: 'Validation Rules ({{type}})',
  minVal: 'min_val (ge)',
  maxVal: 'max_val (le)',
  minLen: 'min_len',
  maxLen: 'max_len',
  regex: 'regex',
  regexPlaceholder: 'e.g. ^[a-z]+$',
} as const;

type TranslationValues = Record<string, number | string>;

function entityText(
  t: TFunction,
  key: string,
  defaultValue: string,
  values: TranslationValues = {}
): string {
  return t(`project.schema.entityTypeList.${key}`, { defaultValue, ...values });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function getStringField(record: Record<string, unknown>, field: string): string | undefined {
  const value = record[field];
  return typeof value === 'string' ? value : undefined;
}

function getNumberField(record: Record<string, unknown>, field: string): number | undefined {
  const value = record[field];
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function getBooleanField(record: Record<string, unknown>, field: string): boolean | undefined {
  const value = record[field];
  return typeof value === 'boolean' ? value : undefined;
}

function toSchemaValue(value: unknown): EntitySchemaValue {
  if (typeof value === 'string') return value;
  if (!isRecord(value)) return { type: 'String' };

  return {
    ...value,
    type: getStringField(value, 'type') ?? 'String',
    description: getStringField(value, 'description') ?? '',
    required: getBooleanField(value, 'required') ?? false,
    ge: getNumberField(value, 'ge'),
    le: getNumberField(value, 'le'),
    min_len: getNumberField(value, 'min_len'),
    max_len: getNumberField(value, 'max_len'),
    regex: getStringField(value, 'regex'),
  };
}

function toEntitySchema(properties: Record<string, unknown> | undefined): EntitySchema {
  if (!properties) return {};

  return Object.fromEntries(
    Object.entries(properties).map(([key, value]) => [key, toSchemaValue(value)])
  );
}

function attributeFromSchemaEntry(name: string, value: EntitySchemaValue): Attribute {
  if (typeof value === 'string') {
    return {
      name,
      type: value,
      description: '',
      required: false,
      validation: {},
    };
  }

  return {
    name,
    type: value.type ?? 'String',
    description: value.description ?? '',
    required: value.required ?? false,
    validation: {
      ge: value.ge,
      le: value.le,
      min_len: value.min_len,
      max_len: value.max_len,
      regex: value.regex,
    },
  };
}

function attributesFromSchema(schema: EntitySchema): Attribute[] {
  return Object.entries(schema).map(([key, value]) => attributeFromSchemaEntry(key, value));
}

// ============================================================================
// Marker Symbols
// ============================================================================

const HeaderMarker = Symbol('EntityTypeList.Header');
const ToolbarMarker = Symbol('EntityTypeList.Toolbar');
const TableMarker = Symbol('EntityTypeList.Table');
const TableHeaderMarker = Symbol('EntityTypeList.TableHeader');
const TableRowMarker = Symbol('EntityTypeList.TableRow');
const StatusBadgeMarker = Symbol('EntityTypeList.StatusBadge');
const SourceBadgeMarker = Symbol('EntityTypeList.SourceBadge');
const EmptyMarker = Symbol('EntityTypeList.Empty');
const LoadingMarker = Symbol('EntityTypeList.Loading');
const ModalMarker = Symbol('EntityTypeList.Modal');

// ============================================================================
// Context
// ============================================================================

interface EntityTypeListState {
  entities: EntityType[];
  loading: boolean;
  loadError: string | null;
  search: string;
  isModalOpen: boolean;
  editingEntity: EntityType | null;
  activeTab: 'general' | 'attributes' | 'relationships';
  formData: EntityTypeFormData;
  attributes: Attribute[];
  isSaving: boolean;
}

interface EntityTypeListActions {
  setSearch: (search: string) => void;
  handleOpenModal: (entity: EntityType | null) => void;
  handleCloseModal: () => void;
  handleSave: () => void;
  handleDelete: (id: string) => void;
  setActiveTab: (tab: 'general' | 'attributes' | 'relationships') => void;
  setFormData: (data: EntityTypeFormData) => void;
  setAttributes: (attrs: Attribute[]) => void;
  addAttribute: () => void;
  updateAttribute: (
    index: number,
    field: AttributeUpdateField,
    value: AttributeUpdateValue
  ) => void;
  removeAttribute: (index: number) => void;
}

interface EntityTypeListContextType {
  state: EntityTypeListState;
  actions: EntityTypeListActions;
}

const EntityTypeListContext = React.createContext<EntityTypeListContextType | null>(null);

const useEntityTypeListContext = (): EntityTypeListContextType => {
  const context = useContext(EntityTypeListContext);
  if (!context) {
    throw new Error('EntityTypeList sub-components must be used within EntityTypeList');
  }
  return context;
};

// Optional hook for testing - returns null if not in context
const useEntityTypeListContextOptional = (): EntityTypeListContextType | null => {
  return useContext(EntityTypeListContext);
};

// ============================================================================
// Main Component
// ============================================================================

interface EntityTypeListProps {
  className?: string | undefined;
}

const EntityTypeListInternal: React.FC<EntityTypeListProps> = ({ className = '' }) => {
  const { t } = useTranslation();
  const { projectId } = useParams<{ projectId: string }>();

  // State
  const [entities, setEntities] = useState<EntityType[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingEntity, setEditingEntity] = useState<EntityType | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [activeTab, setActiveTab] = useState<'general' | 'attributes' | 'relationships'>(
    'attributes'
  );

  // Form state
  const [formData, setFormData] = useState<EntityTypeFormData>({
    name: '',
    description: '',
    schema: {},
  });
  const [attributes, setAttributes] = useState<Attribute[]>([]);
  const formSnapshotRef = useRef('');

  // Load data
  const loadData = useCallback(async () => {
    if (!projectId) return;
    setLoadError(null);
    try {
      const data = await schemaAPI.listEntityTypes(projectId);
      // Convert SchemaEntityType to EntityType
      const loadedAt = new Date().toISOString();
      const entityTypes: EntityType[] = data.map((item) => ({
        id: item.id,
        name: item.name,
        description: item.description ?? '',
        schema: toEntitySchema(item.schema ?? item.properties),
        status: item.status === 'DISABLED' ? 'DISABLED' : 'ENABLED',
        source: item.source === 'generated' ? 'generated' : 'user',
        created_at: item.created_at ?? loadedAt,
        updated_at: item.updated_at ?? item.created_at ?? loadedAt,
      }));
      setEntities(entityTypes);
    } catch (error) {
      logger.error('[EntityTypeList] Failed to load entity types:', error);
      setLoadError(entityText(t, 'loadError', 'Failed to load entity types.'));
    } finally {
      setLoading(false);
    }
  }, [projectId, t]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Handlers
  const handleOpenModal = useCallback((entity: EntityType | null) => {
    const nextFormData: EntityTypeFormData = entity
      ? { name: entity.name, description: entity.description, schema: entity.schema }
      : { name: '', description: '', schema: {} };
    const nextAttributes = entity ? attributesFromSchema(entity.schema) : [];
    setEditingEntity(entity);
    setFormData(nextFormData);
    setAttributes(nextAttributes);
    formSnapshotRef.current = JSON.stringify({
      formData: nextFormData,
      attributes: nextAttributes,
    });
    setActiveTab('attributes');
    setIsModalOpen(true);
  }, []);

  const handleCloseModal = useCallback(async () => {
    const currentSnapshot = JSON.stringify({ formData, attributes });
    if (currentSnapshot !== formSnapshotRef.current) {
      const confirmed = await confirmAction({
        title: entityText(t, 'discardChanges', 'Discard unsaved changes?'),
        danger: true,
      });
      if (!confirmed) return;
    }
    setIsModalOpen(false);
    setEditingEntity(null);
  }, [formData, attributes, t]);

  const handleSave = useCallback(async () => {
    if (!projectId || isSaving) return;

    const trimmedName = formData.name.trim();
    if (!trimmedName) {
      void message.error(entityText(t, 'nameRequired', 'Name is required'));
      return;
    }
    const isDuplicate = entities.some(
      (entity) =>
        entity.name.toLowerCase() === trimmedName.toLowerCase() && entity.id !== editingEntity?.id
    );
    if (isDuplicate) {
      void message.error(
        entityText(t, 'nameDuplicate', 'An entity type with this name already exists')
      );
      return;
    }

    const schemaDict: EntitySchema = {};
    attributes.forEach((attr) => {
      if (attr.name) {
        schemaDict[attr.name] = {
          type: attr.type,
          description: attr.description,
          required: attr.required,
          ...attr.validation,
        };
      }
    });

    const payload = {
      ...formData,
      name: trimmedName,
      schema: schemaDict,
    };

    setIsSaving(true);
    try {
      if (editingEntity) {
        await schemaAPI.updateEntityType(projectId, editingEntity.id, payload);
      } else {
        await schemaAPI.createEntityType(projectId, payload);
      }
      setIsModalOpen(false);
      setEditingEntity(null);
      void loadData();
    } catch (error) {
      logger.error('[EntityTypeList] Failed to save entity type:', error);
      void message.error(entityText(t, 'saveError', 'Failed to save entity type'));
    } finally {
      setIsSaving(false);
    }
  }, [projectId, editingEntity, entities, formData, attributes, isSaving, loadData, t]);

  const handleDelete = useCallback(
    async (id: string) => {
      const target = entities.find((entity) => entity.id === id);
      if (
        !(await confirmAction({
          title: entityText(
            t,
            'deleteConfirmNamed',
            'Delete entity type "{{name}}"? This cannot be undone.',
            { name: target?.name ?? id }
          ),
          danger: true,
        }))
      ) {
        return;
      }
      if (!projectId) return;
      try {
        await schemaAPI.deleteEntityType(projectId, id);
        void loadData();
      } catch (error) {
        logger.error('[EntityTypeList] Failed to delete:', error);
        void message.error(entityText(t, 'deleteError', 'Failed to delete entity type'));
      }
    },
    [projectId, entities, loadData, t]
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

  // Filter entities
  const filteredEntities = useMemo(() => {
    if (!search) return entities;
    const lowerSearch = search.toLowerCase();
    return entities.filter(
      (e) =>
        e.name.toLowerCase().includes(lowerSearch) ||
        e.description.toLowerCase().includes(lowerSearch)
    );
  }, [entities, search]);

  // Context state
  const state: EntityTypeListState = {
    entities,
    loading,
    loadError,
    search,
    isModalOpen,
    editingEntity,
    activeTab,
    formData,
    attributes,
    isSaving,
  };

  // Context actions
  const actions: EntityTypeListActions = {
    setSearch,
    handleOpenModal,
    handleCloseModal: () => {
      void handleCloseModal();
    },
    handleSave: () => {
      void handleSave();
    },
    handleDelete: (id: string) => {
      void handleDelete(id);
    },
    setActiveTab,
    setFormData,
    setAttributes,
    addAttribute,
    updateAttribute,
    removeAttribute,
  };

  if (loading) {
    return <EntityTypeList.Loading />;
  }

  return (
    <EntityTypeListContext.Provider value={{ state, actions }}>
      <div
        className={
          className ||
          'flex flex-col h-full bg-slate-50 dark:bg-background-dark text-slate-900 dark:text-white overflow-hidden'
        }
      >
        <EntityTypeList.Header />
        <div className="flex-1 overflow-y-auto bg-slate-50 dark:bg-background-dark p-8">
          <div className="max-w-7xl mx-auto flex flex-col gap-6">
            <EntityTypeList.Toolbar />
            {loadError ? (
              <div
                role="alert"
                className="flex flex-col items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-center dark:border-red-500/30 dark:bg-red-500/10"
              >
                <p className="text-sm text-red-600 dark:text-red-400">{loadError}</p>
                <button
                  type="button"
                  onClick={() => {
                    void loadData();
                  }}
                  className="inline-flex h-9 items-center rounded-lg bg-slate-950 px-4 text-sm font-medium text-slate-50 transition-colors hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950/20 dark:bg-slate-50 dark:text-slate-950 dark:hover:bg-slate-200 dark:focus-visible:ring-slate-50/20"
                >
                  {entityText(t, 'retry', 'Retry')}
                </button>
              </div>
            ) : (
              <EntityTypeList.Table
                entities={filteredEntities}
                onEdit={actions.handleOpenModal}
                onDelete={actions.handleDelete}
              />
            )}
          </div>
        </div>
        {isModalOpen && (
          <EntityTypeList.Modal
            isOpen={isModalOpen}
            onClose={actions.handleCloseModal}
            onSave={actions.handleSave}
            editingEntity={editingEntity}
          />
        )}
      </div>
    </EntityTypeListContext.Provider>
  );
};

EntityTypeListInternal.displayName = 'EntityTypeList';

// ============================================================================
// Header Sub-Component
// ============================================================================

interface HeaderProps {
  onCreate?: (() => void) | undefined;
}

const HeaderInternal: React.FC<HeaderProps> = (props) => {
  const { t } = useTranslation();
  const contextFromHook = useEntityTypeListContextOptional();
  const hasProps = props.onCreate !== undefined;
  const context = hasProps ? null : contextFromHook;
  const actions = context?.actions;
  const handleCreate = props.onCreate ?? actions?.handleOpenModal;

  if (!handleCreate) return null;

  return (
    <div className="w-full flex-none pt-8 pb-4 px-8 border-b border-slate-200 dark:border-border-dark/50 bg-white dark:bg-background-dark">
      <div className="max-w-7xl mx-auto flex flex-col gap-4">
        <div className="flex flex-wrap justify-between items-center gap-4">
          <div>
            <h2 className="text-slate-900 dark:text-white text-3xl font-bold tracking-tight">
              {entityText(t, 'title', TEXTS.title)}
            </h2>
            <p className="text-slate-500 dark:text-text-muted text-sm mt-1">
              {entityText(t, 'subtitle', TEXTS.subtitle)}
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              handleCreate(null);
            }}
            className="flex items-center gap-2 cursor-pointer rounded-lg h-10 px-5 bg-blue-600 dark:bg-primary hover:bg-blue-700 dark:hover:bg-primary-light text-white text-sm font-bold shadow-lg shadow-blue-900/20 transition-[color,background-color,border-color,box-shadow,opacity]"
          >
            <Plus className="w-5 h-5" />
            <span>{entityText(t, 'createButton', TEXTS.create)}</span>
          </button>
        </div>
      </div>
    </div>
  );
};

HeaderInternal.displayName = 'EntityTypeList.Header';

// ============================================================================
// Toolbar Sub-Component
// ============================================================================

interface ToolbarProps {
  search?: string | undefined;
  onSearchChange?: ((value: string) => void) | undefined;
}

const ToolbarInternal: React.FC<ToolbarProps> = (props) => {
  const { t } = useTranslation();
  const contextFromHook = useEntityTypeListContextOptional();
  const hasProps = props.onSearchChange !== undefined;
  const context = hasProps ? null : contextFromHook;
  const state = context?.state;
  const actions = context?.actions;

  const search = props.search ?? state?.search ?? '';
  const setSearch = props.onSearchChange ?? actions?.setSearch;

  if (!setSearch) return null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-4 bg-white dark:bg-surface-dark p-4 rounded-xl border border-slate-200 dark:border-border-dark">
      <div className="flex flex-1 max-w-md">
        <label className="flex w-full items-center h-10 rounded-lg bg-slate-100 dark:bg-surface-dark-alt border border-transparent focus-within:border-blue-500 dark:focus-within:border-primary/50 transition-colors">
          <div className="text-slate-400 dark:text-text-muted flex items-center justify-center pl-3">
            <Search className="w-5 h-5" aria-hidden="true" />
          </div>
          <input
            aria-label={entityText(t, 'searchPlaceholder', TEXTS.searchPlaceholder)}
            className="w-full bg-transparent border-none text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-text-muted focus:ring-0 text-sm px-3 outline-none"
            placeholder={entityText(t, 'searchPlaceholder', TEXTS.searchPlaceholder)}
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
            }}
          />
        </label>
      </div>
    </div>
  );
};

ToolbarInternal.displayName = 'EntityTypeList.Toolbar';

// ============================================================================
// StatusBadge Sub-Component
// ============================================================================

interface StatusBadgeProps {
  status: string;
}

const StatusBadgeInternal: React.FC<StatusBadgeProps> = React.memo(({ status }) => {
  const { t } = useTranslation();

  return (
    <span
      className={`px-2 py-1 rounded-full text-2xs font-bold uppercase tracking-wide border ${
        status === 'ENABLED'
          ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20'
          : 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-700'
      }`}
    >
      {entityText(t, `status.${status.toLowerCase()}`, status)}
    </span>
  );
});

StatusBadgeInternal.displayName = 'EntityTypeList.StatusBadge';

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
      className={`px-2 py-1 rounded-full text-2xs font-bold uppercase tracking-wide border ${
        sourceKey === 'generated'
          ? 'bg-purple-50 dark:bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-200 dark:border-purple-500/20'
          : 'bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-500/20'
      }`}
    >
      {entityText(t, `source.${sourceKey}`, sourceKey)}
    </span>
  );
});

SourceBadgeInternal.displayName = 'EntityTypeList.SourceBadge';

// ============================================================================
// TableRow Sub-Component
// ============================================================================

interface TableRowProps {
  entity: EntityType;
  onEdit: (entity: EntityType) => void;
  onDelete: (id: string) => void;
}

const TableRowInternal: React.FC<TableRowProps> = React.memo(({ entity, onEdit, onDelete }) => {
  const { t } = useTranslation();
  const handleEdit = useCallback(() => {
    onEdit(entity);
  }, [entity, onEdit]);

  const handleDelete = useCallback(() => {
    onDelete(entity.id);
  }, [entity.id, onDelete]);

  return (
    <div className="grid grid-cols-12 gap-4 px-6 py-4 hover:bg-slate-50 dark:hover:bg-surface-dark-alt transition-colors group items-start">
      <div className="col-span-2 flex items-center gap-4">
        <div className="flex items-center justify-center h-10 w-10 rounded-lg bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-500/20">
          <User className="w-6 h-6" />
        </div>
        <div className="flex flex-col">
          <span className="text-slate-900 dark:text-white font-medium text-sm">{entity.name}</span>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-500"></span>
            <span className="text-xs text-slate-500 dark:text-text-muted">
              {entity.description || entityText(t, 'coreModel', 'Core Model')}
            </span>
          </div>
        </div>
      </div>
      <div className="col-span-2 flex items-center">
        <code className="text-xs font-mono bg-slate-100 dark:bg-background-dark px-2 py-1 rounded text-slate-500 dark:text-text-muted border border-slate-200 dark:border-border-dark">
          {entity.id.slice(0, 8)}…
        </code>
      </div>
      <div className="col-span-3 flex flex-col gap-1.5">
        {Object.entries(entity.schema)
          .slice(0, 3)
          .map(([key, value]) => (
            <div key={key} className="flex items-center gap-2 text-xs">
              <span className="text-emerald-600 dark:text-emerald-300 font-mono">{key}</span>
              <span className="text-slate-500 dark:text-text-muted text-2xs">
                : {typeof value === 'string' ? value : (value.type ?? 'String')}
              </span>
            </div>
          ))}
        {Object.keys(entity.schema).length > 3 && (
          <div className="text-2xs text-slate-500 dark:text-text-muted mt-1 font-medium">
            {entityText(t, 'table.moreAttributes', TEXTS.table.moreAttributes, {
              count: Object.keys(entity.schema).length - 3,
            })}
          </div>
        )}
        {Object.keys(entity.schema).length === 0 && (
          <div className="text-2xs text-slate-400 dark:text-text-muted italic">
            {entityText(t, 'table.noAttributes', TEXTS.table.noAttributes)}
          </div>
        )}
      </div>
      <div className="col-span-1 flex items-center">
        <StatusBadgeInternal status={entity.status} />
      </div>
      <div className="col-span-1 flex items-center">
        <SourceBadgeInternal source={entity.source} />
      </div>
      <div className="col-span-2 flex flex-col justify-start pt-1">
        <span className="text-sm text-slate-700 dark:text-white">
          {formatDateOnly(entity.updated_at)}
        </span>
      </div>
      <div className="col-span-1 flex items-center justify-end gap-2 opacity-80 group-hover:opacity-100 transition-opacity">
        <button
          type="button"
          onClick={handleEdit}
          className="p-2 rounded-lg hover:bg-blue-50 dark:hover:bg-primary/20 text-slate-400 dark:text-text-muted hover:text-blue-600 dark:hover:text-primary transition-colors"
          title={entityText(t, 'edit', TEXTS.edit)}
          aria-label={entityText(t, 'edit', TEXTS.edit)}
        >
          <FileEdit className="w-4 h-4" />
        </button>
        <button
          type="button"
          onClick={handleDelete}
          className="p-2 rounded-lg hover:bg-red-50 dark:hover:bg-red-500/20 text-slate-400 dark:text-text-muted hover:text-red-600 dark:hover:text-red-400 transition-colors"
          title={entityText(t, 'delete', TEXTS.delete)}
          aria-label={entityText(t, 'delete', TEXTS.delete)}
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
});

TableRowInternal.displayName = 'EntityTypeList.TableRow';

// ============================================================================
// Table Sub-Component
// ============================================================================

interface TableProps {
  entities: EntityType[];
  onEdit: (entity: EntityType) => void;
  onDelete: (id: string) => void;
}

const TableInternal: React.FC<TableProps> = React.memo(({ entities, onEdit, onDelete }) => {
  if (entities.length === 0) {
    return <EntityTypeList.Empty />;
  }

  return (
    <div className="flex flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm dark:border-border-dark dark:bg-surface-dark">
      <EntityTypeList.TableHeader />
      <div className="divide-y divide-slate-200 dark:divide-border-dark">
        {entities.map((entity) => (
          <EntityTypeList.TableRow
            key={entity.id}
            entity={entity}
            onEdit={onEdit}
            onDelete={onDelete}
          />
        ))}
      </div>
    </div>
  );
});

TableInternal.displayName = 'EntityTypeList.Table';

// ============================================================================
// TableHeader Sub-Component
// ============================================================================

const TableHeaderInternal: React.FC = React.memo(() => {
  const { t } = useTranslation();

  return (
    <div className="grid grid-cols-12 gap-4 border-b border-slate-200 dark:border-border-dark bg-slate-50 dark:bg-surface-dark-alt/50 px-6 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-text-muted">
      <div className="col-span-2 flex items-center">
        {entityText(t, 'table.entityType', TEXTS.table.entityType)}
      </div>
      <div className="col-span-2 flex items-center">
        {entityText(t, 'table.internalId', TEXTS.table.internalId)}
      </div>
      <div className="col-span-3 flex items-center">
        {entityText(t, 'table.schemaDefinition', TEXTS.table.schemaDefinition)}
      </div>
      <div className="col-span-1 flex items-center">
        {entityText(t, 'table.status', TEXTS.table.status)}
      </div>
      <div className="col-span-1 flex items-center">
        {entityText(t, 'table.source', TEXTS.table.source)}
      </div>
      <div className="col-span-2 flex items-center">
        {entityText(t, 'table.lastModified', TEXTS.table.lastModified)}
      </div>
      <div className="col-span-1 flex items-center justify-end">
        {entityText(t, 'table.actions', TEXTS.table.actions)}
      </div>
    </div>
  );
});

TableHeaderInternal.displayName = 'EntityTypeList.TableHeader';

// ============================================================================
// Empty Sub-Component
// ============================================================================

const EmptyInternal: React.FC = () => {
  const { t } = useTranslation();
  const context = useEntityTypeListContextOptional();

  return (
    <div className="flex flex-col items-center gap-4 px-6 py-10 text-center">
      <p className="text-slate-500 dark:text-text-muted">
        {entityText(t, 'table.empty', TEXTS.table.empty)}
      </p>
      {context && (
        <button
          type="button"
          onClick={() => {
            context.actions.handleOpenModal(null);
          }}
          className="inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-bold text-white transition-colors hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/40 dark:bg-primary dark:hover:bg-primary-light"
        >
          <Plus className="w-4 h-4" aria-hidden="true" />
          {entityText(t, 'createButton', TEXTS.create)}
        </button>
      )}
    </div>
  );
};

EmptyInternal.displayName = 'EntityTypeList.Empty';

// ============================================================================
// Loading Sub-Component
// ============================================================================

const LoadingInternal: React.FC = () => {
  const { t } = useTranslation();

  return (
    <div className="p-8 text-center text-slate-500 dark:text-gray-500">
      {entityText(t, 'loading', TEXTS.loading)}
    </div>
  );
};

LoadingInternal.displayName = 'EntityTypeList.Loading';

// ============================================================================
// Modal Sub-Component
// ============================================================================

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: () => void;
  editingEntity: EntityType | null;
}

const ModalInternal: React.FC<ModalProps> = React.memo(
  ({ isOpen, onClose, onSave, editingEntity }) => {
    const { t } = useTranslation();
    const context = useEntityTypeListContextOptional();
    const [activeTab, setActiveTab] = useState<'general' | 'attributes' | 'relationships'>(
      'attributes'
    );
    const [localFormData, setLocalFormData] = useState<EntityTypeFormData>({
      name: editingEntity ? editingEntity.name : '',
      description: editingEntity ? editingEntity.description : '',
      schema: editingEntity ? editingEntity.schema : {},
    });
    const [localAttributes, setLocalAttributes] = useState<Attribute[]>(
      editingEntity ? attributesFromSchema(editingEntity.schema) : []
    );

    const formData = context?.state.formData ?? localFormData;
    const attributes = context?.state.attributes ?? localAttributes;
    const setFormData = context?.actions.setFormData ?? setLocalFormData;
    const setAttributes = context?.actions.setAttributes ?? setLocalAttributes;

    // Reset form when editingEntity changes
    React.useEffect(() => {
      if (editingEntity) {
        setFormData({
          name: editingEntity.name,
          description: editingEntity.description,
          schema: editingEntity.schema,
        });
        setAttributes(attributesFromSchema(editingEntity.schema));
      } else {
        setFormData({ name: '', description: '', schema: {} });
        setAttributes([]);
      }
      setActiveTab('attributes');
    }, [editingEntity, setAttributes, setFormData]);

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
      definedAttributes: entityText(t, 'modal.definedAttributes', TEXTS.modal.definedAttributes),
      addAttribute: entityText(t, 'modal.addAttribute', TEXTS.modal.addAttribute),
      attributeTitle: (index) =>
        entityText(t, 'modal.attributeTitle', TEXTS.modal.attributeTitle, { index }),
      removeAttribute: entityText(t, 'modal.deleteField', TEXTS.modal.deleteField),
      nameLabel: entityText(t, 'modal.attrNameLabel', TEXTS.modal.attrNameLabel),
      namePlaceholder: entityText(t, 'modal.attrNamePlaceholder', TEXTS.modal.attrNamePlaceholder),
      dataTypeLabel: entityText(t, 'modal.dataTypeLabel', TEXTS.modal.dataTypeLabel),
      requiredLabel: entityText(t, 'modal.required', 'Required'),
      docstringLabel: entityText(t, 'modal.docstringLabel', TEXTS.modal.docstringLabel),
      docstringPlaceholder: entityText(
        t,
        'modal.docstringPlaceholder',
        TEXTS.modal.docstringPlaceholder
      ),
      validationRulesTitle: (type) =>
        entityText(t, 'validationRules', TEXTS.validationRules, { type }),
      minValLabel: entityText(t, 'minVal', TEXTS.minVal),
      maxValLabel: entityText(t, 'maxVal', TEXTS.maxVal),
      minLenLabel: entityText(t, 'minLen', TEXTS.minLen),
      maxLenLabel: entityText(t, 'maxLen', TEXTS.maxLen),
      regexLabel: entityText(t, 'regex', TEXTS.regex),
      regexPlaceholder: entityText(t, 'regexPlaceholder', TEXTS.regexPlaceholder),
    };

    if (!isOpen) return null;

    return (
      <AppModal
        open={isOpen}
        onClose={onClose}
        position="side"
        size="xl"
        ariaLabel={entityText(t, 'modal.close', 'Close entity type editor')}
        title={
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center h-10 w-10 rounded-lg bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-500/20">
              <User className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-900 dark:text-white leading-none">
                {editingEntity
                  ? entityText(t, 'modal.titleEdit', TEXTS.modal.titleEdit, {
                      name: editingEntity.name,
                    })
                  : entityText(t, 'modal.titleNew', TEXTS.modal.titleNew)}
              </h3>
              <p className="text-xs text-slate-500 dark:text-text-muted mt-1 font-mono">
                {editingEntity?.id || entityText(t, 'newId', 'New ID')}
              </p>
            </div>
          </div>
        }
        footer={
          <>
            <div className="mr-auto text-xs text-slate-500 dark:text-text-muted flex items-center gap-1">
              <History className="w-4 h-4" />
              <span>
                {entityText(t, 'modal.lastSaved', TEXTS.modal.lastSaved, {
                  time: editingEntity?.updated_at
                    ? formatDateTime(editingEntity.updated_at)
                    : entityText(t, 'modal.neverSaved', TEXTS.modal.neverSaved),
                })}
              </span>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-slate-500 dark:text-text-muted hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-border-dark rounded-lg hover:bg-slate-100 dark:hover:bg-border-dark transition-colors"
            >
              {entityText(t, 'modal.discard', TEXTS.modal.discard)}
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
                ? entityText(t, 'modal.saving', 'Saving…')
                : entityText(t, 'modal.save', TEXTS.modal.save)}
            </button>
          </>
        }
      >
        <div className="flex-1 overflow-y-auto">
          <div className="flex border-b border-slate-200 dark:border-border-dark sticky top-0 bg-white dark:bg-background-dark z-10 px-6 pt-2">
            <button
              type="button"
              onClick={() => {
                setActiveTab('general');
              }}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'general'
                  ? 'text-blue-600 dark:text-blue-400 border-blue-600 dark:border-blue-400 bg-blue-50 dark:bg-blue-500/5'
                  : 'text-slate-500 dark:text-text-muted border-transparent hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              {entityText(t, 'generalSettings', TEXTS.generalSettings)}
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveTab('attributes');
              }}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'attributes'
                  ? 'text-blue-600 dark:text-blue-400 border-blue-600 dark:border-blue-400 bg-blue-50 dark:bg-blue-500/5'
                  : 'text-slate-500 dark:text-text-muted border-transparent hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              {entityText(t, 'attributesSchema', TEXTS.attributesSchema)}
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveTab('relationships');
              }}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'relationships'
                  ? 'text-blue-600 dark:text-blue-400 border-blue-600 dark:border-blue-400 bg-blue-50 dark:bg-blue-500/5'
                  : 'text-slate-500 dark:text-text-muted border-transparent hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              {entityText(t, 'relationships', TEXTS.relationships)}
            </button>
          </div>

          <div className="p-6 flex flex-col gap-8">
            {activeTab === 'general' && (
              <div className="flex flex-col gap-4">
                <h4 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
                  {entityText(t, 'modal.basicInfo', TEXTS.modal.basicInfo)}
                </h4>
                <div className="grid grid-cols-1 gap-4">
                  <div>
                    <label
                      htmlFor="entity-type-name"
                      className="text-2xs uppercase text-slate-500 dark:text-text-muted font-bold mb-1.5 block"
                    >
                      {entityText(t, 'modal.nameLabel', TEXTS.modal.nameLabel)}
                    </label>
                    <input
                      id="entity-type-name"
                      className="w-full bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-border-dark rounded-lg text-sm text-slate-900 dark:text-white px-3 py-2 font-mono focus:border-blue-600 dark:focus:border-primary focus:ring-1 focus:ring-blue-600 dark:focus:ring-primary outline-none transition-colors"
                      type="text"
                      spellCheck={false}
                      value={formData.name}
                      onChange={(e) => {
                        setFormData({ ...formData, name: e.target.value });
                      }}
                      placeholder={entityText(
                        t,
                        'modal.namePlaceholder',
                        TEXTS.modal.namePlaceholder
                      )}
                      disabled={!!editingEntity}
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="entity-type-description"
                      className="text-2xs uppercase text-slate-500 dark:text-text-muted font-bold mb-1.5 block"
                    >
                      {entityText(t, 'modal.descLabel', TEXTS.modal.descLabel)}
                    </label>
                    <textarea
                      id="entity-type-description"
                      className="w-full bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-border-dark rounded-lg text-sm text-slate-900 dark:text-white px-3 py-2 focus:border-blue-600 dark:focus:border-primary focus:ring-1 focus:ring-blue-600 dark:focus:ring-primary outline-none transition-colors h-32"
                      value={formData.description}
                      onChange={(e) => {
                        setFormData({ ...formData, description: e.target.value });
                      }}
                      placeholder={entityText(
                        t,
                        'modal.descPlaceholder',
                        TEXTS.modal.descPlaceholder
                      )}
                    />
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'attributes' && (
              <>
                <div className="bg-blue-50 dark:bg-blue-500/5 border border-blue-200 dark:border-blue-500/20 rounded-lg p-4 flex gap-3">
                  <Info
                    className="w-5 h-5 text-blue-600 dark:text-blue-400 mt-0.5"
                    aria-hidden="true"
                  />
                  <div className="flex flex-col gap-1">
                    <h4 className="text-sm font-bold text-blue-900 dark:text-blue-100">
                      {entityText(t, 'modal.infoTitle', TEXTS.modal.infoTitle)}
                    </h4>
                    <p className="text-xs text-blue-700 dark:text-blue-200/70">
                      {entityText(t, 'modal.infoDesc', TEXTS.modal.infoDesc)}
                    </p>
                  </div>
                </div>

                <AttributeEditor
                  attributes={attributes}
                  onAdd={addAttribute}
                  onUpdate={updateAttribute}
                  onRemove={removeAttribute}
                  labels={attributeEditorLabels}
                  showRequired
                  showValidation
                />
              </>
            )}

            {activeTab === 'relationships' && (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="bg-slate-100 dark:bg-slate-800 p-4 rounded-full mb-4">
                  <GripVertical className="w-8 h-8 text-slate-400" />
                </div>
                <h3 className="text-lg font-bold text-slate-900 dark:text-white">
                  {entityText(t, 'relationshipMapping', TEXTS.relationshipMapping)}
                </h3>
                <p className="text-sm text-slate-500 dark:text-slate-400 mt-2 max-w-sm">
                  {entityText(t, 'relationshipsComingSoon', TEXTS.relationshipsComingSoon)}
                </p>
              </div>
            )}
          </div>
        </div>
      </AppModal>
    );
  }
);

ModalInternal.displayName = 'EntityTypeList.Modal';

// ============================================================================
// Attach Sub-Components to Main Component
// ============================================================================

const attachMarker = <P extends object>(component: React.FC<P>, marker: symbol): React.FC<P> =>
  Object.assign(component, { [marker]: true });

// Export the compound component
export const EntityTypeList = Object.assign(EntityTypeListInternal, {
  Header: attachMarker(HeaderInternal, HeaderMarker),
  Toolbar: attachMarker(ToolbarInternal, ToolbarMarker),
  Table: attachMarker(TableInternal, TableMarker),
  TableHeader: attachMarker(TableHeaderInternal, TableHeaderMarker),
  TableRow: attachMarker(TableRowInternal, TableRowMarker),
  StatusBadge: attachMarker(StatusBadgeInternal, StatusBadgeMarker),
  SourceBadge: attachMarker(SourceBadgeInternal, SourceBadgeMarker),
  Empty: attachMarker(EmptyInternal, EmptyMarker),
  Loading: attachMarker(LoadingInternal, LoadingMarker),
  Modal: attachMarker(ModalInternal, ModalMarker),
  useContext: useEntityTypeListContext,
});

export default EntityTypeList;
