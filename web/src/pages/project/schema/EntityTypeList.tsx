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

import React, { useCallback, useEffect, useState, useMemo, useContext } from 'react';

import { useParams } from 'react-router-dom';

import {
  Plus,
  Search,
  ChevronDown,
  List,
  Grid,
  User,
  FileEdit,
  X,
  Info,
  History,
  Trash2,
  Gavel,
  GripVertical,
} from 'lucide-react';

import { formatDateOnly, formatDateTime } from '@/utils/date';

import { schemaAPI } from '../../../services/api';

// ============================================================================
// Types
// ============================================================================

export interface EntityType {
  id: string;
  name: string;
  description: string;
  schema: Record<string, any>;
  status: 'ENABLED' | 'DISABLED';
  source: 'user' | 'generated';
  created_at: string;
  updated_at: string;
}

export interface Attribute {
  name: string;
  type: string;
  description: string;
  required: boolean;
  validation: {
    ge?: number;
    le?: number;
    min_len?: number;
    max_len?: number;
    regex?: string;
  };
}

// ============================================================================
// Constants
// ============================================================================

const TEXTS = {
  title: 'Entity Types',
  subtitle: 'Define the structure of entities in your knowledge graph',
  create: 'Create Entity Type',
  searchPlaceholder: 'Search entity types...',
  filterProject: 'Filter Project',
  listView: 'List View',
  gridView: 'Grid View',

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
  loading: 'Loading...',

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
  search: string;
  viewMode: 'list' | 'grid';
  isModalOpen: boolean;
  editingEntity: EntityType | null;
  activeTab: 'general' | 'attributes' | 'relationships';
  formData: {
    name: string;
    description: string;
    schema: Record<string, any>;
  };
  attributes: Attribute[];
}

interface EntityTypeListActions {
  setSearch: (search: string) => void;
  setViewMode: (mode: 'list' | 'grid') => void;
  handleOpenModal: (entity: EntityType | null) => void;
  handleCloseModal: () => void;
  handleSave: () => void;
  handleDelete: (id: string) => void;
  setActiveTab: (tab: 'general' | 'attributes' | 'relationships') => void;
  setFormData: (data: { name: string; description: string; schema: Record<string, any> }) => void;
  setAttributes: (attrs: Attribute[]) => void;
  addAttribute: () => void;
  updateAttribute: (index: number, field: string, value: any) => void;
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
  className?: string;
}

const EntityTypeListInternal: React.FC<EntityTypeListProps> = ({ className = '' }) => {
  const { projectId } = useParams<{ projectId: string }>();

  // State
  const [entities, setEntities] = useState<EntityType[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [viewMode, setViewMode] = useState<'list' | 'grid'>('list');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingEntity, setEditingEntity] = useState<EntityType | null>(null);
  const [activeTab, setActiveTab] = useState<'general' | 'attributes' | 'relationships'>(
    'attributes'
  );

  // Form state
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    schema: {} as Record<string, any>,
  });
  const [attributes, setAttributes] = useState<Attribute[]>([]);

  // Load data
  const loadData = useCallback(async () => {
    if (!projectId) return;
    try {
      const data = await schemaAPI.listEntityTypes(projectId);
      // Convert SchemaEntityType to EntityType
      const entityTypes: EntityType[] = data.map((item) => ({
        id: item.id,
        name: item.name,
        description: item.description || '',
        schema: (item.properties as Record<string, any>) || {},
        status: 'ENABLED' as const,
        source: 'user' as const,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }));
      setEntities(entityTypes);
    } catch (error) {
      console.error('Failed to load entity types:', error);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Handlers
  const handleOpenModal = useCallback((entity: EntityType | null) => {
    if (entity) {
      setEditingEntity(entity);
      const attrs = Object.entries(entity.schema || {}).map(([key, val]: [string, any]) => ({
        name: key,
        type: typeof val === 'string' ? val : val.type || 'String',
        description: typeof val === 'string' ? '' : val.description || '',
        required: typeof val === 'string' ? false : !!val.required,
        validation:
          typeof val === 'string'
            ? {}
            : {
                ge: val.ge,
                le: val.le,
                min_len: val.min_len,
                max_len: val.max_len,
                regex: val.regex,
              },
      }));
      setFormData({
        name: entity.name,
        description: entity.description || '',
        schema: entity.schema,
      });
      setAttributes(attrs);
    } else {
      setEditingEntity(null);
      setFormData({ name: '', description: '', schema: {} });
      setAttributes([]);
    }
    setActiveTab('attributes');
    setIsModalOpen(true);
  }, []);

  const handleCloseModal = useCallback(() => {
    setIsModalOpen(false);
    setEditingEntity(null);
  }, []);

  const handleSave = useCallback(async () => {
    if (!projectId) return;

    const schemaDict: Record<string, any> = {};
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
      schema: schemaDict,
    };

    try {
      if (editingEntity) {
        await schemaAPI.updateEntityType(projectId, editingEntity.id, payload);
      } else {
        await schemaAPI.createEntityType(projectId, payload);
      }
      setIsModalOpen(false);
      setEditingEntity(null);
      loadData();
    } catch (error) {
      console.error('Failed to save entity type:', error);
    }
  }, [projectId, editingEntity, formData, attributes, loadData]);

  const handleDelete = useCallback(
    async (id: string) => {
      if (!confirm(TEXTS.deleteConfirm)) return;
      if (!projectId) return;
      try {
        await schemaAPI.deleteEntityType(projectId, id);
        loadData();
      } catch (error) {
        console.error('Failed to delete:', error);
      }
    },
    [projectId, loadData]
  );

  const addAttribute = useCallback(() => {
    setAttributes([
      ...attributes,
      { name: '', type: 'String', description: '', required: false, validation: {} },
    ]);
  }, [attributes]);

  const updateAttribute = useCallback(
    (index: number, field: string, value: any) => {
      const newAttrs = [...attributes];
      if (field.startsWith('validation.')) {
        const validationField = field.split('.')[1];
        const existing = newAttrs[index];
        if (existing && validationField) {
          newAttrs[index] = {
            ...existing,
            validation: { ...existing.validation, [validationField]: value },
          };
        }
      } else {
        const existing = newAttrs[index];
        if (existing) {
          newAttrs[index] = { ...existing, [field]: value };
        }
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
        e.description?.toLowerCase().includes(lowerSearch)
    );
  }, [entities, search]);

  // Context state
  const state: EntityTypeListState = {
    entities,
    loading,
    search,
    viewMode,
    isModalOpen,
    editingEntity,
    activeTab,
    formData,
    attributes,
  };

  // Context actions
  const actions: EntityTypeListActions = {
    setSearch,
    setViewMode,
    handleOpenModal,
    handleCloseModal,
    handleSave,
    handleDelete,
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
          'flex flex-col h-full bg-slate-50 dark:bg-[#111521] text-slate-900 dark:text-white overflow-hidden'
        }
      >
        <EntityTypeList.Header />
        <div className="flex-1 overflow-y-auto bg-slate-50 dark:bg-[#111521] p-8">
          <div className="max-w-7xl mx-auto flex flex-col gap-6">
            <EntityTypeList.Toolbar />
            <EntityTypeList.Table
              entities={filteredEntities}
              onEdit={actions.handleOpenModal}
              onDelete={actions.handleDelete}
            />
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
  onCreate?: () => void;
}

const HeaderInternal: React.FC<HeaderProps> = (props) => {
  const contextFromHook = useEntityTypeListContextOptional();
  const hasProps = props.onCreate !== undefined;
  const context = hasProps ? null : contextFromHook;
  const actions = context?.actions;
  const handleCreate = props.onCreate ?? actions?.handleOpenModal;

  if (!handleCreate) return null;

  return (
    <div className="w-full flex-none pt-8 pb-4 px-8 border-b border-slate-200 dark:border-[#2a324a]/50 bg-white dark:bg-[#121521]">
      <div className="max-w-7xl mx-auto flex flex-col gap-4">
        <div className="flex flex-wrap justify-between items-center gap-4">
          <div>
            <h2 className="text-slate-900 dark:text-white text-3xl font-bold tracking-tight">
              {TEXTS.title}
            </h2>
            <p className="text-slate-500 dark:text-[#95a0c6] text-sm mt-1">{TEXTS.subtitle}</p>
          </div>
          <button
            onClick={() => handleCreate(null)}
            className="flex items-center gap-2 cursor-pointer rounded-lg h-10 px-5 bg-blue-600 dark:bg-[#193db3] hover:bg-blue-700 dark:hover:bg-[#254bcc] text-white text-sm font-bold shadow-lg shadow-blue-900/20 transition-all active:scale-95"
          >
            <Plus className="w-5 h-5" />
            <span>{TEXTS.create}</span>
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
  search?: string;
  onSearchChange?: (value: string) => void;
  viewMode?: 'list' | 'grid';
  onViewModeChange?: (mode: 'list' | 'grid') => void;
}

const ToolbarInternal: React.FC<ToolbarProps> = (props) => {
  const contextFromHook = useEntityTypeListContextOptional();
  const hasProps = props.onSearchChange !== undefined;
  const context = hasProps ? null : contextFromHook;
  const state = context?.state;
  const actions = context?.actions;

  const search = props.search ?? state?.search ?? '';
  const setSearch = props.onSearchChange ?? actions?.setSearch;
  const viewMode = props.viewMode ?? state?.viewMode ?? 'list';
  const setViewMode = props.onViewModeChange ?? actions?.setViewMode;

  if (!setSearch || !setViewMode) return null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-4 bg-white dark:bg-[#1e2433] p-4 rounded-xl border border-slate-200 dark:border-[#2a324a]">
      <div className="flex flex-1 max-w-md">
        <label className="flex w-full items-center h-10 rounded-lg bg-slate-100 dark:bg-[#252d46] border border-transparent focus-within:border-blue-500 dark:focus-within:border-[#193db3]/50 transition-colors">
          <div className="text-slate-400 dark:text-[#95a0c6] flex items-center justify-center pl-3">
            <Search className="w-5 h-5" />
          </div>
          <input
            className="w-full bg-transparent border-none text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-[#95a0c6] focus:ring-0 text-sm px-3 outline-none"
            placeholder={TEXTS.searchPlaceholder}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
      </div>
      <div className="flex items-center gap-3">
        <button className="flex h-9 items-center gap-2 rounded-lg bg-slate-100 dark:bg-[#252d46] hover:bg-slate-200 dark:hover:bg-[#2f3956] border border-slate-200 dark:border-[#2a324a] px-3 transition-colors">
          <span className="text-slate-700 dark:text-white text-sm font-medium">
            {TEXTS.filterProject}
          </span>
          <ChevronDown className="w-4 h-4 text-slate-400 dark:text-[#95a0c6]" />
        </button>
        <div className="h-6 w-px bg-slate-200 dark:bg-[#2a324a] mx-1"></div>
        <button
          onClick={() => setViewMode('list')}
          className={`flex items-center justify-center h-9 w-9 rounded-lg transition-colors ${
            viewMode === 'list'
              ? 'bg-slate-200 dark:bg-[#252d46] text-slate-900 dark:text-white'
              : 'bg-transparent text-slate-400 dark:text-[#95a0c6] hover:text-slate-900 dark:hover:text-white'
          }`}
          title={TEXTS.listView}
        >
          <List className="w-5 h-5" />
        </button>
        <button
          onClick={() => setViewMode('grid')}
          className={`flex items-center justify-center h-9 w-9 rounded-lg transition-colors ${
            viewMode === 'grid'
              ? 'bg-slate-200 dark:bg-[#252d46] text-slate-900 dark:text-white'
              : 'bg-transparent text-slate-400 dark:text-[#95a0c6] hover:text-slate-900 dark:hover:text-white'
          }`}
          title={TEXTS.gridView}
        >
          <Grid className="w-5 h-5" />
        </button>
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

const StatusBadgeInternal: React.FC<StatusBadgeProps> = React.memo(({ status }) => (
  <span
    className={`px-2 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide border ${
      status === 'ENABLED'
        ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20'
        : 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-700'
    }`}
  >
    {status || 'ENABLED'}
  </span>
));

StatusBadgeInternal.displayName = 'EntityTypeList.StatusBadge';

// ============================================================================
// SourceBadge Sub-Component
// ============================================================================

interface SourceBadgeProps {
  source: string;
}

const SourceBadgeInternal: React.FC<SourceBadgeProps> = React.memo(({ source }) => (
  <span
    className={`px-2 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide border ${
      source === 'generated'
        ? 'bg-purple-50 dark:bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-200 dark:border-purple-500/20'
        : 'bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-500/20'
    }`}
  >
    {source || 'user'}
  </span>
));

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
  const handleEdit = useCallback(() => {
    onEdit(entity);
  }, [entity, onEdit]);

  const handleDelete = useCallback(() => {
    onDelete(entity.id);
  }, [entity.id, onDelete]);

  return (
    <div className="grid grid-cols-12 gap-4 px-6 py-4 hover:bg-slate-50 dark:hover:bg-[#252d46] transition-colors group items-start">
      <div className="col-span-2 flex items-center gap-4">
        <div className="flex items-center justify-center h-10 w-10 rounded-lg bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-500/20">
          <User className="w-6 h-6" />
        </div>
        <div className="flex flex-col">
          <span className="text-slate-900 dark:text-white font-medium text-sm">{entity.name}</span>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-500"></span>
            <span className="text-xs text-slate-500 dark:text-[#95a0c6]">
              {entity.description || 'Core Model'}
            </span>
          </div>
        </div>
      </div>
      <div className="col-span-2 flex items-center">
        <code className="text-xs font-mono bg-slate-100 dark:bg-[#121521] px-2 py-1 rounded text-slate-500 dark:text-[#95a0c6] border border-slate-200 dark:border-[#2a324a]">
          {entity.id.slice(0, 8)}...
        </code>
      </div>
      <div className="col-span-3 flex flex-col gap-1.5">
        {Object.entries(entity.schema || {})
          .slice(0, 3)
          .map(([key, val]: [string, any]) => (
            <div key={key} className="flex items-center gap-2 text-xs">
              <span className="text-emerald-600 dark:text-emerald-300 font-mono">{key}</span>
              <span className="text-slate-500 dark:text-[#95a0c6] text-[10px]">
                : {typeof val === 'string' ? val : val.type}
              </span>
            </div>
          ))}
        {Object.keys(entity.schema || {}).length > 3 && (
          <div className="text-[10px] text-slate-500 dark:text-[#95a0c6] mt-1 font-medium">
            +{Object.keys(entity.schema || {}).length - 3} more
          </div>
        )}
        {Object.keys(entity.schema || {}).length === 0 && (
          <div className="text-[10px] text-slate-400 dark:text-[#95a0c6] italic">
            {TEXTS.table.noAttributes}
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
          {entity.created_at ? formatDateOnly(entity.created_at) : '-'}
        </span>
        <span className="text-xs text-slate-400 dark:text-[#95a0c6]">by Admin</span>
      </div>
      <div className="col-span-1 flex items-center justify-end gap-2 opacity-80 group-hover:opacity-100 transition-opacity">
        <button
          onClick={handleEdit}
          className="p-2 rounded-lg hover:bg-blue-50 dark:hover:bg-[#193db3]/20 text-slate-400 dark:text-[#95a0c6] hover:text-blue-600 dark:hover:text-[#193db3] transition-colors"
          title={TEXTS.edit}
        >
          <FileEdit className="w-4 h-4" />
        </button>
        <button
          onClick={handleDelete}
          className="p-2 rounded-lg hover:bg-red-50 dark:hover:bg-red-500/20 text-slate-400 dark:text-[#95a0c6] hover:text-red-600 dark:hover:text-red-400 transition-colors"
          title={TEXTS.delete}
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
    <div className="flex flex-col rounded-xl border border-slate-200 dark:border-[#2a324a] bg-white dark:bg-[#1e2433] overflow-hidden shadow-xl">
      <EntityTypeList.TableHeader />
      <div className="divide-y divide-slate-200 dark:divide-[#2a324a]">
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

const TableHeaderInternal: React.FC = React.memo(() => (
  <div className="grid grid-cols-12 gap-4 border-b border-slate-200 dark:border-[#2a324a] bg-slate-50 dark:bg-[#252d46]/50 px-6 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-[#95a0c6]">
    <div className="col-span-2 flex items-center">{TEXTS.table.entityType}</div>
    <div className="col-span-2 flex items-center">{TEXTS.table.internalId}</div>
    <div className="col-span-3 flex items-center">{TEXTS.table.schemaDefinition}</div>
    <div className="col-span-1 flex items-center">{TEXTS.table.status}</div>
    <div className="col-span-1 flex items-center">{TEXTS.table.source}</div>
    <div className="col-span-2 flex items-center">{TEXTS.table.lastModified}</div>
    <div className="col-span-1 flex items-center justify-end">{TEXTS.table.actions}</div>
  </div>
));

TableHeaderInternal.displayName = 'EntityTypeList.TableHeader';

// ============================================================================
// Empty Sub-Component
// ============================================================================

const EmptyInternal: React.FC = () => (
  <div className="px-6 py-8 text-center text-slate-500 dark:text-[#95a0c6]">
    {TEXTS.table.empty}
  </div>
);

EmptyInternal.displayName = 'EntityTypeList.Empty';

// ============================================================================
// Loading Sub-Component
// ============================================================================

const LoadingInternal: React.FC = () => (
  <div className="p-8 text-center text-slate-500 dark:text-gray-500">{TEXTS.loading}</div>
);

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
    const [activeTab, setActiveTab] = useState<'general' | 'attributes' | 'relationships'>(
      'attributes'
    );
    const [formData, setFormData] = useState({
      name: editingEntity?.name || '',
      description: editingEntity?.description || '',
      schema: editingEntity?.schema || {},
    });
    const [attributes, setAttributes] = useState<Attribute[]>(
      editingEntity
        ? Object.entries(editingEntity.schema || {}).map(([key, val]: [string, any]) => ({
            name: key,
            type: typeof val === 'string' ? val : val.type || 'String',
            description: typeof val === 'string' ? '' : val.description || '',
            required: typeof val === 'string' ? false : !!val.required,
            validation:
              typeof val === 'string'
                ? {}
                : {
                    ge: val.ge,
                    le: val.le,
                    min_len: val.min_len,
                    max_len: val.max_len,
                    regex: val.regex,
                  },
          }))
        : []
    );

    // Reset form when editingEntity changes
    React.useEffect(() => {
      if (editingEntity) {
        setFormData({
          name: editingEntity.name,
          description: editingEntity.description || '',
          schema: editingEntity.schema,
        });
        setAttributes(
          Object.entries(editingEntity.schema || {}).map(([key, val]: [string, any]) => ({
            name: key,
            type: typeof val === 'string' ? val : val.type || 'String',
            description: typeof val === 'string' ? '' : val.description || '',
            required: typeof val === 'string' ? false : !!val.required,
            validation:
              typeof val === 'string'
                ? {}
                : {
                    ge: val.ge,
                    le: val.le,
                    min_len: val.min_len,
                    max_len: val.max_len,
                    regex: val.regex,
                  },
          }))
        );
      } else {
        setFormData({ name: '', description: '', schema: {} });
        setAttributes([]);
      }
      setActiveTab('attributes');
    }, [editingEntity]);

    const addAttribute = useCallback(() => {
      setAttributes([
        ...attributes,
        { name: '', type: 'String', description: '', required: false, validation: {} },
      ]);
    }, [attributes]);

    const updateAttribute = useCallback(
      (index: number, field: string, value: any) => {
        const newAttrs = [...attributes];
        if (field.startsWith('validation.')) {
          const validationField = field.split('.')[1];
          const existing = newAttrs[index];
          if (existing && validationField) {
            newAttrs[index] = {
              ...existing,
              validation: { ...existing.validation, [validationField]: value },
            };
          }
        } else {
          const existing = newAttrs[index];
          if (existing) {
            newAttrs[index] = { ...existing, [field]: value };
          }
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

    if (!isOpen) return null;

    return (
      <div aria-modal="true" className="fixed inset-0 z-50 flex justify-end" role="dialog">
        <div
          className="absolute inset-0 bg-black/60 backdrop-blur-[2px] transition-opacity"
          onClick={onClose}
        ></div>
        <div
          className="relative w-full max-w-3xl bg-white dark:bg-[#111521] shadow-2xl flex flex-col h-full border-l border-slate-200 dark:border-[#2a324a] animate-in slide-in-from-right duration-300"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-[#2a324a] bg-slate-50 dark:bg-[#1e2433]">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center h-10 w-10 rounded-lg bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-500/20">
                <User className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-slate-900 dark:text-white leading-none">
                  {editingEntity
                    ? `${TEXTS.modal.titleEdit} ${editingEntity.name}`
                    : TEXTS.modal.titleNew}
                </h3>
                <p className="text-xs text-slate-500 dark:text-[#95a0c6] mt-1 font-mono">
                  {editingEntity?.id || 'New ID'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={onClose}
                className="flex items-center justify-center w-8 h-8 rounded-lg text-slate-400 dark:text-[#95a0c6] hover:bg-slate-200 dark:hover:bg-[#2a324a] hover:text-slate-900 dark:hover:text-white transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto">
            <div className="flex border-b border-slate-200 dark:border-[#2a324a] sticky top-0 bg-white dark:bg-[#111521] z-10 px-6 pt-2">
              <button
                onClick={() => setActiveTab('general')}
                className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === 'general'
                    ? 'text-blue-600 dark:text-blue-400 border-blue-600 dark:border-blue-400 bg-blue-50 dark:bg-blue-500/5'
                    : 'text-slate-500 dark:text-[#95a0c6] border-transparent hover:text-slate-900 dark:hover:text-white'
                }`}
              >
                {TEXTS.generalSettings}
              </button>
              <button
                onClick={() => setActiveTab('attributes')}
                className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === 'attributes'
                    ? 'text-blue-600 dark:text-blue-400 border-blue-600 dark:border-blue-400 bg-blue-50 dark:bg-blue-500/5'
                    : 'text-slate-500 dark:text-[#95a0c6] border-transparent hover:text-slate-900 dark:hover:text-white'
                }`}
              >
                {TEXTS.attributesSchema}
              </button>
              <button
                onClick={() => setActiveTab('relationships')}
                className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === 'relationships'
                    ? 'text-blue-600 dark:text-blue-400 border-blue-600 dark:border-blue-400 bg-blue-50 dark:bg-blue-500/5'
                    : 'text-slate-500 dark:text-[#95a0c6] border-transparent hover:text-slate-900 dark:hover:text-white'
                }`}
              >
                {TEXTS.relationships}
              </button>
            </div>

            <div className="p-6 flex flex-col gap-8">
              {activeTab === 'general' && (
                <div className="flex flex-col gap-4">
                  <h4 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
                    {TEXTS.modal.basicInfo}
                  </h4>
                  <div className="grid grid-cols-1 gap-4">
                    <div>
                      <label className="text-[10px] uppercase text-slate-500 dark:text-[#95a0c6] font-bold mb-1.5 block">
                        {TEXTS.modal.nameLabel}
                      </label>
                      <input
                        className="w-full bg-slate-50 dark:bg-[#121521] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm text-slate-900 dark:text-white px-3 py-2 font-mono focus:border-blue-600 dark:focus:border-[#193db3] focus:ring-1 focus:ring-blue-600 dark:focus:ring-[#193db3] outline-none transition-colors"
                        type="text"
                        value={formData.name}
                        onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                        placeholder={TEXTS.modal.namePlaceholder}
                        disabled={!!editingEntity}
                      />
                    </div>
                    <div>
                      <label className="text-[10px] uppercase text-slate-500 dark:text-[#95a0c6] font-bold mb-1.5 block">
                        {TEXTS.modal.descLabel}
                      </label>
                      <textarea
                        className="w-full bg-slate-50 dark:bg-[#121521] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm text-slate-900 dark:text-white px-3 py-2 focus:border-blue-600 dark:focus:border-[#193db3] focus:ring-1 focus:ring-blue-600 dark:focus:ring-[#193db3] outline-none transition-colors h-32"
                        value={formData.description}
                        onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                        placeholder={TEXTS.modal.descPlaceholder}
                      />
                    </div>
                  </div>
                </div>
              )}

              {activeTab === 'attributes' && (
                <>
                  <div className="bg-blue-50 dark:bg-blue-500/5 border border-blue-200 dark:border-blue-500/20 rounded-lg p-4 flex gap-3">
                    <Info className="w-5 h-5 text-blue-600 dark:text-blue-400 mt-0.5" />
                    <div className="flex flex-col gap-1">
                      <h4 className="text-sm font-bold text-blue-900 dark:text-blue-100">
                        {TEXTS.modal.infoTitle}
                      </h4>
                      <p className="text-xs text-blue-700 dark:text-blue-200/70">
                        {TEXTS.modal.infoDesc}
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-col gap-4">
                    <div className="flex items-center justify-between">
                      <h4 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
                        {TEXTS.modal.definedAttributes}
                      </h4>
                      <button
                        onClick={addAttribute}
                        className="text-blue-600 dark:text-[#193db3] text-xs font-bold flex items-center gap-1 hover:text-blue-700 dark:hover:text-[#254bcc] px-3 py-1.5 bg-blue-50 dark:bg-[#193db3]/10 rounded-lg border border-blue-200 dark:border-[#193db3]/20 transition-colors"
                      >
                        <Plus className="w-4 h-4" /> {TEXTS.modal.addAttribute}
                      </button>
                    </div>
                    <div className="flex flex-col gap-4">
                      {attributes.map((attr, idx) => (
                        <div
                          key={idx}
                          className="border border-blue-200 dark:border-[#193db3]/50 bg-white dark:bg-[#1e2433] rounded-xl overflow-hidden shadow-xl shadow-black/5 dark:shadow-black/20 ring-1 ring-blue-100 dark:ring-[#193db3]/30"
                        >
                          <div className="bg-slate-50 dark:bg-[#252d46] px-4 py-2 flex items-center justify-between border-b border-slate-200 dark:border-[#2a324a]">
                            <div className="flex items-center gap-2">
                              <FileEdit className="w-4 h-4 text-blue-600 dark:text-[#193db3]" />
                              <span className="text-xs font-bold text-slate-700 dark:text-white uppercase tracking-wide">
                                Attribute #{idx + 1}
                              </span>
                            </div>
                            <button
                              onClick={() => removeAttribute(idx)}
                              className="text-xs text-red-600 dark:text-red-400 hover:text-red-500 dark:hover:text-red-300 font-medium flex items-center gap-1"
                            >
                              {TEXTS.modal.deleteField}
                            </button>
                          </div>
                          <div className="p-5 flex flex-col gap-6">
                            <div className="grid grid-cols-12 gap-4">
                              <div className="col-span-5">
                                <label className="text-[10px] uppercase text-slate-500 dark:text-[#95a0c6] font-bold mb-1.5 block">
                                  {TEXTS.modal.attrNameLabel}
                                </label>
                                <input
                                  className="w-full bg-slate-50 dark:bg-[#121521] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm text-slate-900 dark:text-white px-3 py-2 font-mono focus:border-blue-600 dark:focus:border-[#193db3] focus:ring-1 focus:ring-blue-600 dark:focus:ring-[#193db3] outline-none transition-colors"
                                  type="text"
                                  value={attr.name}
                                  onChange={(e) => updateAttribute(idx, 'name', e.target.value)}
                                  placeholder={TEXTS.modal.attrNamePlaceholder}
                                />
                              </div>
                              <div className="col-span-4">
                                <label className="text-[10px] uppercase text-slate-500 dark:text-[#95a0c6] font-bold mb-1.5 block">
                                  {TEXTS.modal.dataTypeLabel}
                                </label>
                                <div className="relative">
                                  <select
                                    className="w-full bg-slate-50 dark:bg-[#121521] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm text-slate-900 dark:text-white px-3 py-2 outline-none appearance-none focus:border-blue-600 dark:focus:border-[#193db3]"
                                    value={attr.type}
                                    onChange={(e) => updateAttribute(idx, 'type', e.target.value)}
                                  >
                                    <option value="String">String</option>
                                    <option value="Integer">Integer</option>
                                    <option value="Float">Float</option>
                                    <option value="Boolean">Boolean</option>
                                    <option value="DateTime">DateTime</option>
                                    <option value="List">List</option>
                                    <option value="Dict">Dict</option>
                                  </select>
                                  <ChevronDown className="absolute right-2 top-2.5 w-4 h-4 text-slate-400 dark:text-[#95a0c6] pointer-events-none" />
                                </div>
                              </div>
                              <div className="col-span-3 flex items-end pb-2">
                                <label className="flex items-center gap-2 cursor-pointer select-none">
                                  <input
                                    type="checkbox"
                                    checked={attr.required}
                                    onChange={(e) =>
                                      updateAttribute(idx, 'required', e.target.checked)
                                    }
                                    className="rounded border-slate-300 text-blue-600 focus:ring-blue-500 h-4 w-4"
                                  />
                                  <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                                    Required
                                  </span>
                                </label>
                              </div>
                            </div>
                            <div>
                              <label className="text-[10px] uppercase text-slate-500 dark:text-[#95a0c6] font-bold mb-1.5 block">
                                {TEXTS.modal.docstringLabel}
                              </label>
                              <input
                                className="w-full bg-slate-50 dark:bg-[#121521] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm text-slate-500 dark:text-[#95a0c6] px-3 py-2 focus:text-slate-900 dark:focus:text-white focus:border-blue-600 dark:focus:border-[#193db3] focus:ring-1 focus:ring-blue-600 dark:focus:ring-[#193db3] outline-none transition-colors"
                                type="text"
                                value={attr.description}
                                onChange={(e) =>
                                  updateAttribute(idx, 'description', e.target.value)
                                }
                                placeholder={TEXTS.modal.docstringPlaceholder}
                              />
                            </div>

                            {/* Validation Rules */}
                            <div className="bg-slate-100 dark:bg-[#121521] rounded-lg border border-slate-200 dark:border-[#2a324a] p-4">
                              <div className="flex items-center gap-2 mb-3">
                                <Gavel className="w-4 h-4 text-blue-500" />
                                <span className="text-xs font-bold text-slate-700 dark:text-white uppercase tracking-wider">
                                  Validation Rules ({attr.type})
                                </span>
                              </div>
                              <div className="grid grid-cols-3 gap-4">
                                {(attr.type === 'Integer' || attr.type === 'Float') && (
                                  <>
                                    <div>
                                      <label className="text-[10px] text-slate-500 dark:text-[#95a0c6] block mb-1 font-mono">
                                        min_val (ge)
                                      </label>
                                      <input
                                        type="number"
                                        className="w-full bg-white dark:bg-[#1e2433] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm px-2 py-1.5 focus:border-blue-600 focus:ring-0"
                                        value={attr.validation?.ge || ''}
                                        onChange={(e) =>
                                          updateAttribute(
                                            idx,
                                            'validation.ge',
                                            e.target.value ? Number(e.target.value) : undefined
                                          )
                                        }
                                      />
                                    </div>
                                    <div>
                                      <label className="text-[10px] text-slate-500 dark:text-[#95a0c6] block mb-1 font-mono">
                                        max_val (le)
                                      </label>
                                      <input
                                        type="number"
                                        className="w-full bg-white dark:bg-[#1e2433] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm px-2 py-1.5 focus:border-blue-600 focus:ring-0"
                                        value={attr.validation?.le || ''}
                                        onChange={(e) =>
                                          updateAttribute(
                                            idx,
                                            'validation.le',
                                            e.target.value ? Number(e.target.value) : undefined
                                          )
                                        }
                                      />
                                    </div>
                                  </>
                                )}
                                {attr.type === 'String' && (
                                  <>
                                    <div>
                                      <label className="text-[10px] text-slate-500 dark:text-[#95a0c6] block mb-1 font-mono">
                                        min_len
                                      </label>
                                      <input
                                        type="number"
                                        className="w-full bg-white dark:bg-[#1e2433] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm px-2 py-1.5 focus:border-blue-600 focus:ring-0"
                                        value={attr.validation?.min_len || ''}
                                        onChange={(e) =>
                                          updateAttribute(
                                            idx,
                                            'validation.min_len',
                                            e.target.value ? Number(e.target.value) : undefined
                                          )
                                        }
                                      />
                                    </div>
                                    <div>
                                      <label className="text-[10px] text-slate-500 dark:text-[#95a0c6] block mb-1 font-mono">
                                        max_len
                                      </label>
                                      <input
                                        type="number"
                                        className="w-full bg-white dark:bg-[#1e2433] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm px-2 py-1.5 focus:border-blue-600 focus:ring-0"
                                        value={attr.validation?.max_len || ''}
                                        onChange={(e) =>
                                          updateAttribute(
                                            idx,
                                            'validation.max_len',
                                            e.target.value ? Number(e.target.value) : undefined
                                          )
                                        }
                                      />
                                    </div>
                                    <div className="col-span-2">
                                      <label className="text-[10px] text-slate-500 dark:text-[#95a0c6] block mb-1 font-mono">
                                        regex
                                      </label>
                                      <input
                                        type="text"
                                        className="w-full bg-white dark:bg-[#1e2433] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm px-2 py-1.5 focus:border-blue-600 focus:ring-0"
                                        placeholder="e.g. ^[a-z]+$"
                                        value={attr.validation?.regex || ''}
                                        onChange={(e) =>
                                          updateAttribute(idx, 'validation.regex', e.target.value)
                                        }
                                      />
                                    </div>
                                  </>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              )}

              {activeTab === 'relationships' && (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <div className="bg-slate-100 dark:bg-slate-800 p-4 rounded-full mb-4">
                    <GripVertical className="w-8 h-8 text-slate-400" />
                  </div>
                  <h3 className="text-lg font-bold text-slate-900 dark:text-white">
                    {TEXTS.relationshipMapping}
                  </h3>
                  <p className="text-sm text-slate-500 dark:text-slate-400 mt-2 max-w-sm">
                    {TEXTS.relationshipsComingSoon}
                  </p>
                </div>
              )}
            </div>
          </div>
          <div className="border-t border-slate-200 dark:border-[#2a324a] p-4 bg-slate-50 dark:bg-[#1e2433] flex justify-between items-center gap-3">
            <div className="text-xs text-slate-500 dark:text-[#95a0c6] flex items-center gap-1">
              <History className="w-4 h-4" />
              <span>
                {TEXTS.modal.lastSaved.replace(
                  '{{time}}',
                  editingEntity?.updated_at
                    ? formatDateTime(editingEntity.updated_at)
                    : TEXTS.modal.neverSaved
                )}
              </span>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-slate-500 dark:text-[#95a0c6] hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-[#2a324a] rounded-lg hover:bg-slate-100 dark:hover:bg-[#2a324a] transition-colors"
              >
                {TEXTS.modal.discard}
              </button>
              <button
                onClick={onSave}
                className="px-5 py-2 text-sm font-bold text-white bg-blue-600 dark:bg-[#193db3] rounded-lg hover:bg-blue-700 dark:hover:bg-[#254bcc] shadow-lg shadow-blue-900/20 transition-all active:scale-95"
              >
                {TEXTS.modal.save}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }
);

ModalInternal.displayName = 'EntityTypeList.Modal';

// ============================================================================
// Attach Sub-Components to Main Component
// ============================================================================

const attachMarker = <P extends object>(component: React.FC<P>, marker: symbol) => {
  (component as any)[marker] = true;
  return component;
};

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
