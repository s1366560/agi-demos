import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { schemaAPI } from '../../../services/api';
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
    GripVertical
} from 'lucide-react';

export default function EntityTypeList() {
    const { projectId } = useParams<{ projectId: string }>();
    const { t } = useTranslation();
    const [entities, setEntities] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingEntity, setEditingEntity] = useState<any>(null);
    const [viewMode, setViewMode] = useState<'list' | 'grid'>('list');
    const [activeTab, setActiveTab] = useState<'general' | 'attributes' | 'relationships'>('attributes');

    // Form state
    const [formData, setFormData] = useState({
        name: '',
        description: '',
        schema: {} as Record<string, any>
    });

    // Attribute builder state
    const [attributes, setAttributes] = useState<{ 
        name: string, 
        type: string, 
        description: string, 
        required: boolean,
        validation: {
            ge?: number;
            le?: number;
            min_len?: number;
            max_len?: number;
            regex?: string;
        }
    }[]>([]);

    const loadData = useCallback(async () => {
        if (!projectId) return;
        try {
            const data = await schemaAPI.listEntityTypes(projectId);
            setEntities(data);
        } catch (error) {
            console.error('Failed to load entity types:', error);
        } finally {
            setLoading(false);
        }
    }, [projectId]);

    useEffect(() => {
        loadData();
    }, [loadData]);

    const handleOpenModal = (entity: any = null) => {
        if (entity) {
            setEditingEntity(entity);
            // Parse schema back to attributes list
            const attrs = Object.entries(entity.schema || {}).map(([key, val]: [string, any]) => ({
                name: key,
                type: typeof val === 'string' ? val : val.type || 'String',
                description: typeof val === 'string' ? '' : val.description || '',
                required: typeof val === 'string' ? false : !!val.required,
                validation: typeof val === 'string' ? {} : {
                    ge: val.ge,
                    le: val.le,
                    min_len: val.min_len,
                    max_len: val.max_len,
                    regex: val.regex
                }
            }));
            setFormData({
                name: entity.name,
                description: entity.description || '',
                schema: entity.schema
            });
            setAttributes(attrs);
        } else {
            setEditingEntity(null);
            setFormData({ name: '', description: '', schema: {} });
            setAttributes([]);
        }
        setActiveTab('attributes'); // Default tab
        setIsModalOpen(true);
    };

    const handleSave = async () => {
        if (!projectId) return;

        // Convert attributes to schema dict
        const schemaDict: Record<string, any> = {};
        attributes.forEach(attr => {
            if (attr.name) {
                schemaDict[attr.name] = {
                    type: attr.type,
                    description: attr.description,
                    required: attr.required,
                    ...attr.validation
                };
            }
        });

        const payload = {
            ...formData,
            schema: schemaDict
        };

        try {
            if (editingEntity) {
                await schemaAPI.updateEntityType(projectId, editingEntity.id, payload);
            } else {
                await schemaAPI.createEntityType(projectId, payload);
            }
            setIsModalOpen(false);
            loadData();
        } catch (error) {
            console.error('Failed to save entity type:', error);
            alert(t('project.schema.entities.save_error'));
        }
    };

    const handleDelete = async (id: string) => {
        if (!confirm(t('project.schema.entities.delete_confirm'))) return;
        if (!projectId) return;
        try {
            await schemaAPI.deleteEntityType(projectId, id);
            loadData();
        } catch (error) {
            console.error('Failed to delete:', error);
        }
    };

    const addAttribute = () => {
        setAttributes([...attributes, { name: '', type: 'String', description: '', required: false, validation: {} }]);
    };

    const updateAttribute = (index: number, field: string, value: any) => {
        const newAttrs = [...attributes];
        if (field.startsWith('validation.')) {
            const validationField = field.split('.')[1];
            newAttrs[index] = { 
                ...newAttrs[index], 
                validation: { ...newAttrs[index].validation, [validationField]: value } 
            };
        } else {
            newAttrs[index] = { ...newAttrs[index], [field]: value };
        }
        setAttributes(newAttrs);
    };

    const removeAttribute = (index: number) => {
        setAttributes(attributes.filter((_, i) => i !== index));
    };

    if (loading) return <div className="p-8 text-center text-slate-500 dark:text-gray-500">{t('common.loading')}</div>;

    return (
        <div className="flex flex-col h-full bg-slate-50 dark:bg-[#111521] text-slate-900 dark:text-white overflow-hidden">
            {/* Header Section */}
            <div className="w-full flex-none pt-8 pb-4 px-8 border-b border-slate-200 dark:border-[#2a324a]/50 bg-white dark:bg-[#121521]">
                <div className="max-w-7xl mx-auto flex flex-col gap-4">
                    <div className="flex flex-wrap justify-between items-center gap-4">
                        <div>
                            <h2 className="text-slate-900 dark:text-white text-3xl font-bold tracking-tight">{t('project.schema.entities.title')}</h2>
                            <p className="text-slate-500 dark:text-[#95a0c6] text-sm mt-1">{t('project.schema.entities.subtitle')}</p>
                        </div>
                        <button
                            onClick={() => handleOpenModal()}
                            className="flex items-center gap-2 cursor-pointer rounded-lg h-10 px-5 bg-blue-600 dark:bg-[#193db3] hover:bg-blue-700 dark:hover:bg-[#254bcc] text-white text-sm font-bold shadow-lg shadow-blue-900/20 transition-all active:scale-95"
                        >
                            <Plus className="w-5 h-5" />
                            <span>{t('project.schema.entities.create')}</span>
                        </button>
                    </div>
                </div>
            </div>

            {/* Content Section */}
            <div className="flex-1 overflow-y-auto bg-slate-50 dark:bg-[#111521] p-8">
                <div className="max-w-7xl mx-auto flex flex-col gap-6">
                    {/* Toolbar */}
                    <div className="flex flex-wrap items-center justify-between gap-4 bg-white dark:bg-[#1e2433] p-4 rounded-xl border border-slate-200 dark:border-[#2a324a]">
                        <div className="flex flex-1 max-w-md">
                            <label className="flex w-full items-center h-10 rounded-lg bg-slate-100 dark:bg-[#252d46] border border-transparent focus-within:border-blue-500 dark:focus-within:border-[#193db3]/50 transition-colors">
                                <div className="text-slate-400 dark:text-[#95a0c6] flex items-center justify-center pl-3">
                                    <Search className="w-5 h-5" />
                                </div>
                                <input className="w-full bg-transparent border-none text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-[#95a0c6] focus:ring-0 text-sm px-3 outline-none" placeholder={t('project.schema.entities.search_placeholder')} />
                            </label>
                        </div>
                        <div className="flex items-center gap-3">
                            <button className="flex h-9 items-center gap-2 rounded-lg bg-slate-100 dark:bg-[#252d46] hover:bg-slate-200 dark:hover:bg-[#2f3956] border border-slate-200 dark:border-[#2a324a] px-3 transition-colors">
                                <span className="text-slate-700 dark:text-white text-sm font-medium">{t('project.schema.entities.filter_project')}</span>
                                <ChevronDown className="w-4 h-4 text-slate-400 dark:text-[#95a0c6]" />
                            </button>
                            <div className="h-6 w-px bg-slate-200 dark:bg-[#2a324a] mx-1"></div>
                            <button
                                onClick={() => setViewMode('list')}
                                className={`flex items-center justify-center h-9 w-9 rounded-lg transition-colors ${viewMode === 'list' ? 'bg-slate-200 dark:bg-[#252d46] text-slate-900 dark:text-white' : 'bg-transparent text-slate-400 dark:text-[#95a0c6] hover:text-slate-900 dark:hover:text-white'}`}
                                title="List View"
                            >
                                <List className="w-5 h-5" />
                            </button>
                            <button
                                onClick={() => setViewMode('grid')}
                                className={`flex items-center justify-center h-9 w-9 rounded-lg transition-colors ${viewMode === 'grid' ? 'bg-slate-200 dark:bg-[#252d46] text-slate-900 dark:text-white' : 'bg-transparent text-slate-400 dark:text-[#95a0c6] hover:text-slate-900 dark:hover:text-white'}`}
                                title="Grid View"
                            >
                                <Grid className="w-5 h-5" />
                            </button>
                        </div>
                    </div>

                    {/* List View */}
                    <div className="flex flex-col rounded-xl border border-slate-200 dark:border-[#2a324a] bg-white dark:bg-[#1e2433] overflow-hidden shadow-xl">
                        <div className="grid grid-cols-12 gap-4 border-b border-slate-200 dark:border-[#2a324a] bg-slate-50 dark:bg-[#252d46]/50 px-6 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-[#95a0c6]">
                            <div className="col-span-2 flex items-center">{t('project.schema.entities.table.entity_type')}</div>
                            <div className="col-span-2 flex items-center">{t('project.schema.entities.table.internal_id')}</div>
                            <div className="col-span-3 flex items-center">{t('project.schema.entities.table.schema_definition')}</div>
                            <div className="col-span-1 flex items-center">{t('project.schema.entities.table.status')}</div>
                            <div className="col-span-1 flex items-center">{t('project.schema.entities.table.source')}</div>
                            <div className="col-span-2 flex items-center">{t('project.schema.entities.table.last_modified')}</div>
                            <div className="col-span-1 flex items-center justify-end">{t('project.schema.entities.table.actions')}</div>
                        </div>
                        <div className="divide-y divide-slate-200 dark:divide-[#2a324a]">
                            {entities.map((entity) => (
                                <div key={entity.id} className="grid grid-cols-12 gap-4 px-6 py-4 hover:bg-slate-50 dark:hover:bg-[#252d46] transition-colors group items-start">
                                    <div className="col-span-2 flex items-center gap-4">
                                        <div className="flex items-center justify-center h-10 w-10 rounded-lg bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-500/20">
                                            <User className="w-6 h-6" />
                                        </div>
                                        <div className="flex flex-col">
                                            <span className="text-slate-900 dark:text-white font-medium text-sm">{entity.name}</span>
                                            <div className="flex items-center gap-2 mt-0.5">
                                                <span className="h-1.5 w-1.5 rounded-full bg-blue-500"></span>
                                                <span className="text-xs text-slate-500 dark:text-[#95a0c6]">{entity.description || 'Core Model'}</span>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="col-span-2 flex items-center">
                                        <code className="text-xs font-mono bg-slate-100 dark:bg-[#121521] px-2 py-1 rounded text-slate-500 dark:text-[#95a0c6] border border-slate-200 dark:border-[#2a324a]">
                                            {entity.id.slice(0, 8)}...
                                        </code>
                                    </div>
                                    <div className="col-span-3 flex flex-col gap-1.5">
                                        {Object.entries(entity.schema || {}).slice(0, 3).map(([key, val]: [string, any]) => (
                                            <div key={key} className="flex items-center gap-2 text-xs">
                                                <span className="text-emerald-600 dark:text-emerald-300 font-mono">{key}</span>
                                                <span className="text-slate-500 dark:text-[#95a0c6] text-[10px]">: {typeof val === 'string' ? val : val.type}</span>
                                            </div>
                                        ))}
                                        {Object.keys(entity.schema || {}).length > 3 && (
                                            <div className="text-[10px] text-slate-500 dark:text-[#95a0c6] mt-1 font-medium">{t('project.schema.entities.table.more_attributes', { count: Object.keys(entity.schema || {}).length - 3 })}</div>
                                        )}
                                        {Object.keys(entity.schema || {}).length === 0 && (
                                            <div className="text-[10px] text-slate-400 dark:text-[#95a0c6] italic">{t('project.schema.entities.table.no_attributes')}</div>
                                        )}
                                    </div>
                                    <div className="col-span-1 flex items-center">
                                        <span className={`px-2 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide border ${entity.status === 'ENABLED'
                                                ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20'
                                                : 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-700'
                                            }`}>
                                            {entity.status || 'ENABLED'}
                                        </span>
                                    </div>
                                    <div className="col-span-1 flex items-center">
                                        <span className={`px-2 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide border ${entity.source === 'generated'
                                                ? 'bg-purple-50 dark:bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-200 dark:border-purple-500/20'
                                                : 'bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-500/20'
                                            }`}>
                                            {entity.source || 'user'}
                                        </span>
                                    </div>
                                    <div className="col-span-2 flex flex-col justify-start pt-1">
                                        <span className="text-sm text-slate-700 dark:text-white">{new Date(entity.created_at || Date.now()).toLocaleDateString()}</span>
                                        <span className="text-xs text-slate-400 dark:text-[#95a0c6]">by Admin</span>
                                    </div>
                                    <div className="col-span-1 flex items-center justify-end gap-2 opacity-80 group-hover:opacity-100 transition-opacity">
                                        <button
                                            onClick={() => handleOpenModal(entity)}
                                            className="p-2 rounded-lg hover:bg-blue-50 dark:hover:bg-[#193db3]/20 text-slate-400 dark:text-[#95a0c6] hover:text-blue-600 dark:hover:text-[#193db3] transition-colors"
                                            title={t('common.edit')}
                                        >
                                            <FileEdit className="w-4 h-4" />
                                        </button>
                                        <button
                                            onClick={() => handleDelete(entity.id)}
                                            className="p-2 rounded-lg hover:bg-red-50 dark:hover:bg-red-500/20 text-slate-400 dark:text-[#95a0c6] hover:text-red-600 dark:hover:text-red-400 transition-colors"
                                            title={t('common.delete')}
                                        >
                                            <Trash2 className="w-4 h-4" />
                                        </button>
                                    </div>
                                </div>
                            ))}
                            {entities.length === 0 && (
                                <div className="px-6 py-8 text-center text-slate-500 dark:text-[#95a0c6]">
                                    {t('project.schema.entities.table.empty')}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            {/* Modal */}
            {isModalOpen && (
                <div aria-modal="true" className="fixed inset-0 z-50 flex justify-end" role="dialog">
                    <div className="absolute inset-0 bg-black/60 backdrop-blur-[2px] transition-opacity" onClick={() => setIsModalOpen(false)}></div>
                    <div className="relative w-full max-w-3xl bg-white dark:bg-[#111521] shadow-2xl flex flex-col h-full border-l border-slate-200 dark:border-[#2a324a] animate-in slide-in-from-right duration-300" onClick={e => e.stopPropagation()}>
                        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-[#2a324a] bg-slate-50 dark:bg-[#1e2433]">
                            <div className="flex items-center gap-4">
                                <div className="flex items-center justify-center h-10 w-10 rounded-lg bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-500/20">
                                    <User className="w-6 h-6" />
                                </div>
                                <div>
                                    <h3 className="text-lg font-bold text-slate-900 dark:text-white leading-none">
                                        {editingEntity ? t('project.schema.entities.modal.title_edit', { name: editingEntity.name }) : t('project.schema.entities.modal.title_new')}
                                    </h3>
                                    <p className="text-xs text-slate-500 dark:text-[#95a0c6] mt-1 font-mono">{editingEntity?.id || 'New ID'}</p>
                                </div>
                            </div>
                            <div className="flex items-center gap-3">
                                <button
                                    onClick={() => setIsModalOpen(false)}
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
                                    className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${activeTab === 'general' ? 'text-blue-600 dark:text-blue-400 border-blue-600 dark:border-blue-400 bg-blue-50 dark:bg-blue-500/5' : 'text-slate-500 dark:text-[#95a0c6] border-transparent hover:text-slate-900 dark:hover:text-white'}`}
                                >
                                    General Settings
                                </button>
                                <button 
                                    onClick={() => setActiveTab('attributes')}
                                    className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${activeTab === 'attributes' ? 'text-blue-600 dark:text-blue-400 border-blue-600 dark:border-blue-400 bg-blue-50 dark:bg-blue-500/5' : 'text-slate-500 dark:text-[#95a0c6] border-transparent hover:text-slate-900 dark:hover:text-white'}`}
                                >
                                    Attributes & Schema
                                </button>
                                <button 
                                    onClick={() => setActiveTab('relationships')}
                                    className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${activeTab === 'relationships' ? 'text-blue-600 dark:text-blue-400 border-blue-600 dark:border-blue-400 bg-blue-50 dark:bg-blue-500/5' : 'text-slate-500 dark:text-[#95a0c6] border-transparent hover:text-slate-900 dark:hover:text-white'}`}
                                >
                                    Relationships
                                </button>
                            </div>
                            
                            <div className="p-6 flex flex-col gap-8">
                                {activeTab === 'general' && (
                                    <div className="flex flex-col gap-4">
                                        <h4 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">{t('project.schema.entities.modal.basic_info')}</h4>
                                        <div className="grid grid-cols-1 gap-4">
                                            <div>
                                                <label className="text-[10px] uppercase text-slate-500 dark:text-[#95a0c6] font-bold mb-1.5 block">{t('project.schema.entities.modal.name_label')}</label>
                                                <input
                                                    className="w-full bg-slate-50 dark:bg-[#121521] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm text-slate-900 dark:text-white px-3 py-2 font-mono focus:border-blue-600 dark:focus:border-[#193db3] focus:ring-1 focus:ring-blue-600 dark:focus:ring-[#193db3] outline-none transition-colors"
                                                    type="text"
                                                    value={formData.name}
                                                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                                    placeholder={t('project.schema.entities.modal.name_placeholder')}
                                                    disabled={!!editingEntity}
                                                />
                                            </div>
                                            <div>
                                                <label className="text-[10px] uppercase text-slate-500 dark:text-[#95a0c6] font-bold mb-1.5 block">{t('project.schema.entities.modal.desc_label')}</label>
                                                <textarea
                                                    className="w-full bg-slate-50 dark:bg-[#121521] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm text-slate-900 dark:text-white px-3 py-2 focus:border-blue-600 dark:focus:border-[#193db3] focus:ring-1 focus:ring-blue-600 dark:focus:ring-[#193db3] outline-none transition-colors h-32"
                                                    value={formData.description}
                                                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                                    placeholder={t('project.schema.entities.modal.desc_placeholder')}
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
                                                <h4 className="text-sm font-bold text-blue-900 dark:text-blue-100">{t('project.schema.entities.modal.info_title')}</h4>
                                                <p className="text-xs text-blue-700 dark:text-blue-200/70">{t('project.schema.entities.modal.info_desc')}</p>
                                            </div>
                                        </div>

                                        <div className="flex flex-col gap-4">
                                            <div className="flex items-center justify-between">
                                                <h4 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">{t('project.schema.entities.modal.defined_attributes')}</h4>
                                                <button
                                                    onClick={addAttribute}
                                                    className="text-blue-600 dark:text-[#193db3] text-xs font-bold flex items-center gap-1 hover:text-blue-700 dark:hover:text-[#254bcc] px-3 py-1.5 bg-blue-50 dark:bg-[#193db3]/10 rounded-lg border border-blue-200 dark:border-[#193db3]/20 transition-colors"
                                                >
                                                    <Plus className="w-4 h-4" /> {t('project.schema.entities.modal.add_attribute')}
                                                </button>
                                            </div>
                                            <div className="flex flex-col gap-4">
                                                {attributes.map((attr, idx) => (
                                                    <div key={idx} className="border border-blue-200 dark:border-[#193db3]/50 bg-white dark:bg-[#1e2433] rounded-xl overflow-hidden shadow-xl shadow-black/5 dark:shadow-black/20 ring-1 ring-blue-100 dark:ring-[#193db3]/30">
                                                        <div className="bg-slate-50 dark:bg-[#252d46] px-4 py-2 flex items-center justify-between border-b border-slate-200 dark:border-[#2a324a]">
                                                            <div className="flex items-center gap-2">
                                                                <FileEdit className="w-4 h-4 text-blue-600 dark:text-[#193db3]" />
                                                                <span className="text-xs font-bold text-slate-700 dark:text-white uppercase tracking-wide">{t('project.schema.entities.modal.attribute_title', { index: idx + 1 })}</span>
                                                            </div>
                                                            <button
                                                                onClick={() => removeAttribute(idx)}
                                                                className="text-xs text-red-600 dark:text-red-400 hover:text-red-500 dark:hover:text-red-300 font-medium flex items-center gap-1"
                                                            >
                                                                {t('project.schema.entities.modal.delete_field')}
                                                            </button>
                                                        </div>
                                                        <div className="p-5 flex flex-col gap-6">
                                                            <div className="grid grid-cols-12 gap-4">
                                                                <div className="col-span-5">
                                                                    <label className="text-[10px] uppercase text-slate-500 dark:text-[#95a0c6] font-bold mb-1.5 block">{t('project.schema.entities.modal.attr_name_label')}</label>
                                                                    <input
                                                                        className="w-full bg-slate-50 dark:bg-[#121521] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm text-slate-900 dark:text-white px-3 py-2 font-mono focus:border-blue-600 dark:focus:border-[#193db3] focus:ring-1 focus:ring-blue-600 dark:focus:ring-[#193db3] outline-none transition-colors"
                                                                        type="text"
                                                                        value={attr.name}
                                                                        onChange={(e) => updateAttribute(idx, 'name', e.target.value)}
                                                                        placeholder={t('project.schema.entities.modal.attr_name_placeholder')}
                                                                    />
                                                                </div>
                                                                <div className="col-span-4">
                                                                    <label className="text-[10px] uppercase text-slate-500 dark:text-[#95a0c6] font-bold mb-1.5 block">{t('project.schema.entities.modal.data_type_label')}</label>
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
                                                                            onChange={(e) => updateAttribute(idx, 'required', e.target.checked)}
                                                                            className="rounded border-slate-300 text-blue-600 focus:ring-blue-500 h-4 w-4"
                                                                        />
                                                                        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">Required</span>
                                                                    </label>
                                                                </div>
                                                            </div>
                                                            <div>
                                                                <label className="text-[10px] uppercase text-slate-500 dark:text-[#95a0c6] font-bold mb-1.5 block">{t('project.schema.entities.modal.docstring_label')}</label>
                                                                <input
                                                                    className="w-full bg-slate-50 dark:bg-[#121521] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm text-slate-500 dark:text-[#95a0c6] px-3 py-2 focus:text-slate-900 dark:focus:text-white focus:border-blue-600 dark:focus:border-[#193db3] focus:ring-1 focus:ring-blue-600 dark:focus:ring-[#193db3] outline-none transition-colors"
                                                                    type="text"
                                                                    value={attr.description}
                                                                    onChange={(e) => updateAttribute(idx, 'description', e.target.value)}
                                                                    placeholder={t('project.schema.entities.modal.docstring_placeholder')}
                                                                />
                                                            </div>

                                                            {/* Validation Rules */}
                                                            <div className="bg-slate-100 dark:bg-[#121521] rounded-lg border border-slate-200 dark:border-[#2a324a] p-4">
                                                                <div className="flex items-center gap-2 mb-3">
                                                                    <Gavel className="w-4 h-4 text-blue-500" />
                                                                    <span className="text-xs font-bold text-slate-700 dark:text-white uppercase tracking-wider">Validation Rules ({attr.type})</span>
                                                                </div>
                                                                <div className="grid grid-cols-3 gap-4">
                                                                    {(attr.type === 'Integer' || attr.type === 'Float') && (
                                                                        <>
                                                                            <div>
                                                                                <label className="text-[10px] text-slate-500 dark:text-[#95a0c6] block mb-1 font-mono">min_val (ge)</label>
                                                                                <input 
                                                                                    type="number" 
                                                                                    className="w-full bg-white dark:bg-[#1e2433] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm px-2 py-1.5 focus:border-blue-600 focus:ring-0"
                                                                                    value={attr.validation?.ge || ''}
                                                                                    onChange={(e) => updateAttribute(idx, 'validation.ge', e.target.value ? Number(e.target.value) : undefined)}
                                                                                />
                                                                            </div>
                                                                            <div>
                                                                                <label className="text-[10px] text-slate-500 dark:text-[#95a0c6] block mb-1 font-mono">max_val (le)</label>
                                                                                <input 
                                                                                    type="number"
                                                                                    className="w-full bg-white dark:bg-[#1e2433] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm px-2 py-1.5 focus:border-blue-600 focus:ring-0"
                                                                                    value={attr.validation?.le || ''}
                                                                                    onChange={(e) => updateAttribute(idx, 'validation.le', e.target.value ? Number(e.target.value) : undefined)}
                                                                                />
                                                                            </div>
                                                                        </>
                                                                    )}
                                                                    {attr.type === 'String' && (
                                                                        <>
                                                                            <div>
                                                                                <label className="text-[10px] text-slate-500 dark:text-[#95a0c6] block mb-1 font-mono">min_len</label>
                                                                                <input 
                                                                                    type="number"
                                                                                    className="w-full bg-white dark:bg-[#1e2433] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm px-2 py-1.5 focus:border-blue-600 focus:ring-0"
                                                                                    value={attr.validation?.min_len || ''}
                                                                                    onChange={(e) => updateAttribute(idx, 'validation.min_len', e.target.value ? Number(e.target.value) : undefined)}
                                                                                />
                                                                            </div>
                                                                            <div>
                                                                                <label className="text-[10px] text-slate-500 dark:text-[#95a0c6] block mb-1 font-mono">max_len</label>
                                                                                <input 
                                                                                    type="number"
                                                                                    className="w-full bg-white dark:bg-[#1e2433] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm px-2 py-1.5 focus:border-blue-600 focus:ring-0"
                                                                                    value={attr.validation?.max_len || ''}
                                                                                    onChange={(e) => updateAttribute(idx, 'validation.max_len', e.target.value ? Number(e.target.value) : undefined)}
                                                                                />
                                                                            </div>
                                                                            <div className="col-span-2">
                                                                                <label className="text-[10px] text-slate-500 dark:text-[#95a0c6] block mb-1 font-mono">regex</label>
                                                                                <input 
                                                                                    type="text"
                                                                                    className="w-full bg-white dark:bg-[#1e2433] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm px-2 py-1.5 focus:border-blue-600 focus:ring-0"
                                                                                    placeholder="e.g. ^[a-z]+$"
                                                                                    value={attr.validation?.regex || ''}
                                                                                    onChange={(e) => updateAttribute(idx, 'validation.regex', e.target.value)}
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
                                        <h3 className="text-lg font-bold text-slate-900 dark:text-white">Relationship Mapping</h3>
                                        <p className="text-sm text-slate-500 dark:text-slate-400 mt-2 max-w-sm">
                                            Define how this entity type connects to others. This feature is coming in the next update.
                                        </p>
                                    </div>
                                )}
                            </div>
                        </div>
                        <div className="border-t border-slate-200 dark:border-[#2a324a] p-4 bg-slate-50 dark:bg-[#1e2433] flex justify-between items-center gap-3">
                            <div className="text-xs text-slate-500 dark:text-[#95a0c6] flex items-center gap-1">
                                <History className="w-4 h-4" />
                                <span>{t('project.schema.entities.modal.last_saved', { time: editingEntity?.updated_at ? new Date(editingEntity.updated_at).toLocaleString() : t('project.schema.entities.modal.never_saved') })}</span>
                            </div>
                            <div className="flex items-center gap-3">
                                <button
                                    onClick={() => setIsModalOpen(false)}
                                    className="px-4 py-2 text-sm font-medium text-slate-500 dark:text-[#95a0c6] hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-[#2a324a] rounded-lg hover:bg-slate-100 dark:hover:bg-[#2a324a] transition-colors"
                                >
                                    {t('project.schema.entities.modal.discard')}
                                </button>
                                <button
                                    onClick={handleSave}
                                    className="px-5 py-2 text-sm font-bold text-white bg-blue-600 dark:bg-[#193db3] rounded-lg hover:bg-blue-700 dark:hover:bg-[#254bcc] shadow-lg shadow-blue-900/20 transition-all active:scale-95"
                                >
                                    {t('project.schema.entities.modal.save')}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
