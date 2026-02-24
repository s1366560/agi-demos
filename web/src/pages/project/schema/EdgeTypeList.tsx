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

import { useParams } from 'react-router-dom';

import {
  Plus,
  Search,
  Filter,
  Download,
  Code,
  Info,
  Pencil,
  Share2,
  Trash2,
  X,
  FileEdit,
  ChevronDown,
  History,
} from 'lucide-react';

import { formatDateTime } from '@/utils/date';

import { schemaAPI } from '../../../services/api';

// ============================================================================
// Types
// ============================================================================

export interface EdgeType {
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
}

// ============================================================================
// Constants
// ============================================================================

const TEXTS = {
  title: 'Edge Types',
  subtitle: 'Define the structure of relationships in your knowledge graph',
  create: 'Create Edge Type',
  searchPlaceholder: 'Search edge types...',
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
  loading: 'Loading...',
};

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
  search: string;
  selectedEdgeId: string | null;
  isModalOpen: boolean;
  editingEdge: EdgeType | null;
  formData: {
    name: string;
    description: string;
    schema: Record<string, any>;
  };
  attributes: Attribute[];
}

interface EdgeTypeListActions {
  setSearch: (search: string) => void;
  setSelectedEdgeId: (id: string | null) => void;
  handleOpenModal: (edge: EdgeType | null) => void;
  handleCloseModal: () => void;
  handleSave: () => void;
  handleDelete: (id: string) => void;
  setFormData: (data: { name: string; description: string; schema: Record<string, any> }) => void;
  setAttributes: (attrs: Attribute[]) => void;
  addAttribute: () => void;
  updateAttribute: (index: number, field: string, value: any) => void;
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
  const { projectId } = useParams<{ projectId: string }>();

  // State
  const [edges, setEdges] = useState<EdgeType[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingEdge, setEditingEdge] = useState<EdgeType | null>(null);

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
      const data = await schemaAPI.listEdgeTypes(projectId);
      // Convert SchemaEdgeType to EdgeType
      const edgeTypes: EdgeType[] = data.map((item) => ({
        id: item.id,
        name: item.name,
        description: item.description || '',
        schema: {},
        status: 'ENABLED' as const,
        source: 'user' as const,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }));
      setEdges(edgeTypes);
      if (edgeTypes.length > 0 && !selectedEdgeId) {
        setSelectedEdgeId(edgeTypes[0]?.id ?? null);
      }
    } catch (error) {
      console.error('Failed to load edge types:', error);
    } finally {
      setLoading(false);
    }
  }, [projectId, selectedEdgeId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Handlers
  const handleOpenModal = useCallback((edge: EdgeType | null) => {
    if (edge) {
      setEditingEdge(edge);
      const attrs = Object.entries(edge.schema || {}).map(([key, val]: [string, any]) => ({
        name: key,
        type: typeof val === 'string' ? val : val.type || 'String',
        description: typeof val === 'string' ? '' : val.description || '',
        required: typeof val === 'string' ? false : !!val.required,
      }));
      setFormData({
        name: edge.name,
        description: edge.description || '',
        schema: edge.schema,
      });
      setAttributes(attrs);
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
    if (!projectId) return;

    const schemaDict: Record<string, any> = {};
    attributes.forEach((attr) => {
      if (attr.name) {
        schemaDict[attr.name] = {
          type: attr.type,
          description: attr.description,
          required: attr.required,
        };
      }
    });

    const payload = {
      ...formData,
      schema: schemaDict,
    };

    try {
      if (editingEdge) {
        await schemaAPI.updateEdgeType(projectId, editingEdge.id, payload);
      } else {
        await schemaAPI.createEdgeType(projectId, payload);
      }
      setIsModalOpen(false);
      setEditingEdge(null);
      loadData();
    } catch (error) {
      console.error('Failed to save edge type:', error);
      alert('Failed to save edge type');
    }
  }, [projectId, editingEdge, formData, attributes, loadData]);

  const handleDelete = useCallback(
    async (id: string) => {
      if (!confirm(TEXTS.deleteConfirm)) return;
      if (!projectId) return;
      try {
        await schemaAPI.deleteEdgeType(projectId, id);
        if (selectedEdgeId === id) {
          setSelectedEdgeId(null);
        }
        loadData();
      } catch (error) {
        console.error('Failed to delete:', error);
      }
    },
    [projectId, selectedEdgeId, loadData]
  );

  const addAttribute = useCallback(() => {
    setAttributes([...attributes, { name: '', type: 'String', description: '', required: false }]);
  }, [attributes]);

  const updateAttribute = useCallback(
    (index: number, field: string, value: any) => {
      const newAttrs = [...attributes];
      const existing = newAttrs[index];
      if (existing) {
        newAttrs[index] = { ...existing, [field]: value };
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
        e.description?.toLowerCase().includes(lowerSearch)
    );
  }, [edges, search]);

  // Context state
  const state: EdgeTypeListState = {
    edges,
    loading,
    search,
    selectedEdgeId,
    isModalOpen,
    editingEdge,
    formData,
    attributes,
  };

  // Context actions
  const actions: EdgeTypeListActions = {
    setSearch,
    setSelectedEdgeId,
    handleOpenModal,
    handleCloseModal,
    handleSave,
    handleDelete,
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
          'flex flex-col h-full bg-slate-50 dark:bg-[#111521] text-slate-900 dark:text-white overflow-hidden'
        }
      >
        <EdgeTypeList.Header />
        <div className="flex-1 overflow-y-auto bg-slate-50 dark:bg-[#111521] p-8">
          <div className="max-w-[1600px] mx-auto flex flex-col bg-white dark:bg-[#1e2128] rounded-xl border border-slate-200 dark:border-[#2d3748] overflow-hidden shadow-xl min-h-[600px]">
            <EdgeTypeList.Toolbar />
            <div className="flex flex-1 overflow-hidden h-[600px]">
              <EdgeTypeList.MasterPane edges={filteredEdges} onSelect={actions.setSelectedEdgeId} />
              <EdgeTypeList.DetailPane
                selectedEdgeId={selectedEdgeId}
                edges={filteredEdges}
                onEdit={actions.handleOpenModal}
                onDelete={actions.handleDelete}
              />
            </div>
          </div>
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
  return (
    <div className="w-full flex-none pt-6 pb-4 px-8 border-b border-slate-200 dark:border-[#2a324a]/50 bg-white dark:bg-[#121521]">
      <div className="max-w-[1600px] mx-auto flex flex-col gap-4">
        <div className="flex flex-wrap justify-between items-end gap-4">
          <div className="flex flex-col gap-2 max-w-2xl">
            <h1 className="text-slate-900 dark:text-white text-3xl font-black leading-tight tracking-tight">
              {TEXTS.title}
            </h1>
            <p className="text-slate-500 dark:text-[#95a0c6] text-base font-normal">
              {TEXTS.subtitle}
            </p>
          </div>
          <div className="flex gap-2">
            <span className="px-3 py-1 rounded-full bg-green-50 dark:bg-green-500/10 text-green-600 dark:text-green-400 text-xs font-medium border border-green-200 dark:border-green-500/20">
              {TEXTS.systemActive}
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
  const contextFromHook = useEdgeTypeListContextOptional();
  const hasProps = props.onSearchChange !== undefined;
  const context = hasProps ? null : contextFromHook;
  const state = context?.state;
  const actions = context?.actions;

  const search = props.search ?? state?.search ?? '';
  const setSearch = props.onSearchChange ?? actions?.setSearch;
  const handleCreate = props.onCreate ?? actions?.handleOpenModal;

  return (
    <div className="flex flex-wrap justify-between items-center gap-4 px-6 py-4 border-b border-slate-200 dark:border-[#2d3748] bg-slate-50 dark:bg-[#181b25]">
      <div className="flex items-center gap-3 flex-1">
        <div className="relative group">
          <div className="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none">
            <Search className="text-slate-400 dark:text-[#95a0c6] w-5 h-5" />
          </div>
          <input
            className="bg-white dark:bg-[#121521] border border-slate-200 dark:border-[#2d3748] text-slate-900 dark:text-white text-sm rounded-lg focus:ring-blue-600 dark:focus:ring-[#193db3] focus:border-blue-600 dark:focus:border-[#193db3] block w-64 pl-10 p-2.5 placeholder-slate-400 dark:placeholder-gray-500 transition-all focus:w-80 outline-none"
            placeholder={TEXTS.searchPlaceholder}
            type="text"
            value={search}
            onChange={(e) => setSearch?.(e.target.value)}
          />
        </div>
        <div className="h-6 w-px bg-slate-200 dark:bg-[#2d3748] mx-2"></div>
        <button
          className="p-2 text-slate-500 dark:text-[#95a0c6] hover:text-slate-900 dark:hover:text-white hover:bg-slate-200 dark:hover:bg-white/5 rounded-lg transition-colors"
          title="Filter"
        >
          <Filter className="w-5 h-5" />
        </button>
        <button
          className="p-2 text-slate-500 dark:text-[#95a0c6] hover:text-slate-900 dark:hover:text-white hover:bg-slate-200 dark:hover:bg-white/5 rounded-lg transition-colors"
          title="Download Schema"
        >
          <Download className="w-5 h-5" />
        </button>
      </div>
      <button
        onClick={() => handleCreate?.(null)}
        className="flex items-center justify-center gap-2 bg-blue-600 dark:bg-[#193db3] hover:bg-blue-700 text-white px-4 py-2.5 rounded-lg text-sm font-bold shadow-lg shadow-blue-900/20 transition-all active:scale-95"
      >
        <Plus className="w-5 h-5" />
        <span>{TEXTS.create}</span>
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

const StatusBadgeInternal: React.FC<StatusBadgeProps> = React.memo(({ status }) => (
  <span
    className={`px-2 py-0.5 rounded-full text-xs font-bold uppercase tracking-wide border ${
      status === 'ENABLED'
        ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20'
        : 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-700'
    }`}
  >
    {status || 'ENABLED'}
  </span>
));

StatusBadgeInternal.displayName = 'EdgeTypeList.StatusBadge';

// ============================================================================
// SourceBadge Sub-Component
// ============================================================================

interface SourceBadgeProps {
  source: string;
}

const SourceBadgeInternal: React.FC<SourceBadgeProps> = React.memo(({ source }) => (
  <span
    className={`px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider font-bold ${
      source === 'generated'
        ? 'bg-purple-50 dark:bg-purple-500/10 text-purple-600 dark:text-purple-400 border border-purple-200 dark:border-purple-500/20'
        : 'bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-500/20'
    }`}
  >
    {source === 'generated' ? 'AUTO' : 'USER'}
  </span>
));

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
    if (edges.length === 0) {
      return <EdgeTypeList.Empty />;
    }

    return (
      <div className="w-1/3 border-r border-slate-200 dark:border-[#2d3748] overflow-y-auto bg-slate-50 dark:bg-[#151820]">
        {edges.map((edge) => (
          <div
            key={edge.id}
            onClick={() => { onSelect(edge.id); }}
            className={`p-4 border-b border-slate-200 dark:border-[#2d3748] cursor-pointer transition-colors border-l-4 ${
              selectedEdgeId === edge.id
                ? 'bg-blue-50 dark:bg-[#193db3]/10 border-l-blue-600 dark:border-l-[#193db3] hover:bg-blue-100 dark:hover:bg-[#193db3]/20'
                : 'border-l-transparent hover:bg-slate-100 dark:hover:bg-white/5'
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
                <span className="text-[10px] uppercase tracking-wider text-blue-600 dark:text-[#193db3] font-bold bg-blue-100 dark:bg-[#193db3]/20 px-1.5 py-0.5 rounded">
                  {TEXTS.master.active}
                </span>
              )}
            </div>
            <p className="text-slate-500 dark:text-[#95a0c6] text-xs mb-3 line-clamp-2">
              {edge.description || TEXTS.master.noDescription}
            </p>
            <div className="flex items-center gap-4 text-xs text-slate-500 dark:text-[#95a0c6]">
              <div className="flex items-center gap-1">
                <Code className="w-3.5 h-3.5" />
                <span>
                  {TEXTS.master.attributesCount.replace(
                    '{{count}}',
                    String(Object.keys(edge.schema || {}).length)
                  )}
                </span>
              </div>
            </div>
          </div>
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
    const selectedEdge = edges.find((e) => e.id === selectedEdgeId);

    if (!selectedEdge) {
      return (
        <div className="flex-1 overflow-y-auto bg-white dark:bg-[#1e2128] p-8">
          <div className="flex flex-col items-center justify-center h-full text-slate-400 dark:text-[#95a0c6]">
            <Share2 className="w-12 h-12 mb-4 opacity-50" />
            <p>{TEXTS.detail.selectPrompt}</p>
          </div>
        </div>
      );
    }

    return (
      <div className="flex-1 overflow-y-auto bg-white dark:bg-[#1e2128] p-8">
        {/* Detail Header */}
        <div className="flex justify-between items-start mb-8 pb-6 border-b border-slate-200 dark:border-[#2d3748]">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <h2 className="text-2xl font-bold text-slate-900 dark:text-white">
                {selectedEdge.name}
              </h2>
              <div title={`ID: ${selectedEdge.id}`}>
                <Info className="text-slate-400 dark:text-[#95a0c6] cursor-help w-5 h-5" />
              </div>
              <div className="flex gap-2 ml-2">
                <EdgeTypeList.StatusBadge status={selectedEdge.status} />
                <EdgeTypeList.SourceBadge source={selectedEdge.source} />
              </div>
            </div>
            <p className="text-slate-500 dark:text-[#95a0c6] text-sm max-w-xl">
              {selectedEdge.description || TEXTS.detail.noDescription}
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => { onDelete(selectedEdge.id); }}
              className="px-3 py-1.5 text-sm font-medium text-slate-500 dark:text-[#95a0c6] hover:text-red-600 dark:hover:text-red-400 border border-slate-200 dark:border-[#2d3748] rounded bg-white dark:bg-[#151820] hover:bg-slate-50 dark:hover:bg-[#252d46] transition-colors flex items-center gap-2"
            >
              <Trash2 className="w-4 h-4" />
              {TEXTS.detail.delete}
            </button>
            <button
              onClick={() => { onEdit(selectedEdge); }}
              className="px-3 py-1.5 text-sm font-medium text-white bg-blue-600 dark:bg-[#193db3] hover:bg-blue-700 rounded transition-colors flex items-center gap-2"
            >
              <Pencil className="w-4 h-4" />
              {TEXTS.detail.edit}
            </button>
          </div>
        </div>

        {/* Attributes Section */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white flex items-center gap-2">
              <Code className="text-blue-600 dark:text-[#193db3] w-5 h-5" />
              {TEXTS.detail.attributesTitle}
            </h3>
            <span className="text-xs text-slate-500 dark:text-[#95a0c6] font-mono bg-slate-100 dark:bg-[#121521] px-2 py-1 rounded border border-slate-200 dark:border-[#2d3748]">
              class {selectedEdge.name}(Edge)
            </span>
          </div>
          <div className="border border-slate-200 dark:border-[#2d3748] rounded-lg overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 dark:bg-[#151820] text-slate-500 dark:text-[#95a0c6] border-b border-slate-200 dark:border-[#2d3748]">
                <tr>
                  <th className="px-4 py-3 font-medium">{TEXTS.detail.table.name}</th>
                  <th className="px-4 py-3 font-medium">{TEXTS.detail.table.type}</th>
                  <th className="px-4 py-3 font-medium">{TEXTS.detail.table.description}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-[#2d3748] bg-white dark:bg-[#121521]/50">
                {Object.entries(selectedEdge.schema || {}).map(([key, val]: [string, any]) => (
                  <tr
                    key={key}
                    className="group hover:bg-slate-50 dark:hover:bg-white/5 transition-colors"
                  >
                    <td className="px-4 py-3 text-slate-900 dark:text-white font-mono text-xs">
                      {key}
                    </td>
                    <td className="px-4 py-3 text-purple-600 dark:text-purple-400 font-mono text-xs">
                      {typeof val === 'string' ? val : val.type}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-[#95a0c6] text-xs">
                      {typeof val === 'string' ? '' : val.description}
                    </td>
                  </tr>
                ))}
                {Object.keys(selectedEdge.schema || {}).length === 0 && (
                  <tr>
                    <td
                      colSpan={3}
                      className="px-4 py-8 text-center text-slate-500 dark:text-[#95a0c6]"
                    >
                      {TEXTS.detail.table.empty}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            <div className="bg-slate-50 dark:bg-[#151820] px-4 py-2 border-t border-slate-200 dark:border-[#2d3748]">
              <button
                onClick={() => { onEdit(selectedEdge); }}
                className="text-xs text-blue-600 dark:text-[#193db3] font-bold flex items-center gap-1 hover:text-blue-800 dark:hover:text-white transition-colors"
              >
                <Plus className="w-4 h-4" />
                {TEXTS.detail.addAttribute}
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

const EmptyInternal: React.FC = () => (
  <div className="p-6 text-center text-slate-500 dark:text-[#95a0c6] text-sm">
    {TEXTS.master.empty}
  </div>
);

EmptyInternal.displayName = 'EdgeTypeList.Empty';

// ============================================================================
// Loading Sub-Component
// ============================================================================

const LoadingInternal: React.FC = () => (
  <div className="p-8 text-center text-slate-500 dark:text-gray-500">{TEXTS.loading}</div>
);

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
    const [formData, setFormData] = useState({
      name: editingEdge?.name || '',
      description: editingEdge?.description || '',
      schema: editingEdge?.schema || {},
    });
    const [attributes, setAttributes] = useState<Attribute[]>(
      editingEdge
        ? Object.entries(editingEdge.schema || {}).map(([key, val]: [string, any]) => ({
            name: key,
            type: typeof val === 'string' ? val : val.type || 'String',
            description: typeof val === 'string' ? '' : val.description || '',
            required: typeof val === 'string' ? false : !!val.required,
          }))
        : []
    );

    // Reset form when editingEntity changes
    React.useEffect(() => {
      if (editingEdge) {
        setFormData({
          name: editingEdge.name,
          description: editingEdge.description || '',
          schema: editingEdge.schema,
        });
        setAttributes(
          Object.entries(editingEdge.schema || {}).map(([key, val]: [string, any]) => ({
            name: key,
            type: typeof val === 'string' ? val : val.type || 'String',
            description: typeof val === 'string' ? '' : val.description || '',
            required: typeof val === 'string' ? false : !!val.required,
          }))
        );
      } else {
        setFormData({ name: '', description: '', schema: {} });
        setAttributes([]);
      }
    }, [editingEdge]);

    const addAttribute = useCallback(() => {
      setAttributes([
        ...attributes,
        { name: '', type: 'String', description: '', required: false },
      ]);
    }, [attributes]);

    const updateAttribute = useCallback(
      (index: number, field: string, value: any) => {
        const newAttrs = [...attributes];
        const existing = newAttrs[index];
        if (existing) {
          newAttrs[index] = { ...existing, [field]: value };
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
          onClick={(e) => { e.stopPropagation(); }}
        >
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-[#2a324a] bg-slate-50 dark:bg-[#1e2433]">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center h-10 w-10 rounded-lg bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-500/20">
                <Share2 className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-slate-900 dark:text-white leading-none">
                  {editingEdge
                    ? TEXTS.modal.titleEdit.replace('{{name}}', editingEdge.name)
                    : TEXTS.modal.titleNew}
                </h3>
                <p className="text-xs text-slate-500 dark:text-[#95a0c6] mt-1 font-mono">
                  {editingEdge?.id || 'New ID'}
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
              <button className="px-4 py-3 text-sm font-bold text-blue-600 dark:text-blue-400 border-b-2 border-blue-600 dark:border-blue-400 transition-colors bg-blue-50 dark:bg-blue-500/5">
                {TEXTS.modal.tabAttributes}
              </button>
            </div>
            <div className="p-6 flex flex-col gap-8">
              {/* Basic Info */}
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
                      onChange={(e) => { setFormData({ ...formData, name: e.target.value }); }}
                      placeholder={TEXTS.modal.namePlaceholder}
                      disabled={!!editingEdge}
                    />
                  </div>
                  <div>
                    <label className="text-[10px] uppercase text-slate-500 dark:text-[#95a0c6] font-bold mb-1.5 block">
                      {TEXTS.modal.descLabel}
                    </label>
                    <input
                      className="w-full bg-slate-50 dark:bg-[#121521] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm text-slate-900 dark:text-white px-3 py-2 focus:border-blue-600 dark:focus:border-[#193db3] focus:ring-1 focus:ring-blue-600 dark:focus:ring-[#193db3] outline-none transition-colors"
                      type="text"
                      value={formData.description}
                      onChange={(e) => { setFormData({ ...formData, description: e.target.value }); }}
                      placeholder={TEXTS.modal.descPlaceholder}
                    />
                  </div>
                </div>
              </div>

              {/* Attributes */}
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
                            {TEXTS.modal.attributeTitle.replace('{{index}}', String(idx + 1))}
                          </span>
                        </div>
                        <button
                          onClick={() => { removeAttribute(idx); }}
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
                              onChange={(e) => { updateAttribute(idx, 'name', e.target.value); }}
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
                                onChange={(e) => { updateAttribute(idx, 'type', e.target.value); }}
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
                        </div>
                        <div>
                          <label className="text-[10px] uppercase text-slate-500 dark:text-[#95a0c6] font-bold mb-1.5 block">
                            {TEXTS.modal.docstringLabel}
                          </label>
                          <input
                            className="w-full bg-slate-50 dark:bg-[#121521] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm text-slate-500 dark:text-[#95a0c6] px-3 py-2 focus:text-slate-900 dark:focus:text-white focus:border-blue-600 dark:focus:border-[#193db3] focus:ring-1 focus:ring-blue-600 dark:focus:ring-[#193db3] outline-none transition-colors"
                            type="text"
                            value={attr.description}
                            onChange={(e) => { updateAttribute(idx, 'description', e.target.value); }}
                            placeholder={TEXTS.modal.docstringPlaceholder}
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
          <div className="border-t border-slate-200 dark:border-[#2a324a] p-4 bg-slate-50 dark:bg-[#1e2433] flex justify-between items-center gap-3">
            <div className="text-xs text-slate-500 dark:text-[#95a0c6] flex items-center gap-1">
              <History className="w-4 h-4" />
              <span>
                {TEXTS.modal.lastSaved.replace(
                  '{{time}}',
                  editingEdge?.updated_at
                    ? formatDateTime(editingEdge.updated_at)
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

ModalInternal.displayName = 'EdgeTypeList.Modal';

// ============================================================================
// Attach Sub-Components to Main Component
// ============================================================================

const attachMarker = <P extends object>(component: React.FC<P>, marker: symbol) => {
  (component as any)[marker] = true;
  return component;
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
