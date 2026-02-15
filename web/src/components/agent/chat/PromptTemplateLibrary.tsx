/**
 * PromptTemplateLibrary - Quick-access template prompts
 *
 * A popover library of categorized prompt templates that users can
 * insert into the chat input with one click. Supports search/filter.
 * Shows both built-in and user-created custom templates.
 *
 * Inspired by Cursor's template library and Notion's slash commands.
 */

import { memo, useState, useCallback, useRef, useEffect, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Code2,
  FileText,
  BarChart3,
  Lightbulb,
  Search,
  X,
  ArrowRight,
  Layers,
  Trash2,
  User,
  Loader2,
} from 'lucide-react';

import { useTemplateStore, useTemplateActions } from '@/stores/templateStore';
import { useCurrentTenant } from '@/stores/tenant';

import type { PromptTemplateData } from '@/services/templateService';

import { VariableInputModal } from './VariableInputModal';


export interface PromptTemplate {
  id: string;
  titleKey: string;
  titleFallback: string;
  promptKey: string;
  promptFallback: string;
  category: TemplateCategory;
  icon?: string;
}

export type TemplateCategory = 'analysis' | 'code' | 'writing' | 'general';

const categoryConfig: Record<TemplateCategory, { icon: React.ReactNode; colorClass: string }> = {
  analysis: {
    icon: <BarChart3 size={14} />,
    colorClass: 'text-blue-500 bg-blue-50 dark:bg-blue-950/30',
  },
  code: {
    icon: <Code2 size={14} />,
    colorClass: 'text-emerald-500 bg-emerald-50 dark:bg-emerald-950/30',
  },
  writing: {
    icon: <FileText size={14} />,
    colorClass: 'text-slate-500 bg-slate-50 dark:bg-slate-800/30',
  },
  general: {
    icon: <Lightbulb size={14} />,
    colorClass: 'text-slate-500 bg-slate-50 dark:bg-slate-800/30',
  },
};

const defaultTemplates: PromptTemplate[] = [
  // Analysis
  {
    id: 'analyze-codebase',
    titleKey: 'agent.templates.analyzeCodebase',
    titleFallback: 'Analyze Codebase',
    promptKey: 'agent.templates.analyzeCodebasePrompt',
    promptFallback: 'Analyze the codebase structure and provide a high-level overview including architecture patterns, key dependencies, and areas for improvement.',
    category: 'analysis',
  },
  {
    id: 'find-bugs',
    titleKey: 'agent.templates.findBugs',
    titleFallback: 'Find Bugs',
    promptKey: 'agent.templates.findBugsPrompt',
    promptFallback: 'Search for potential bugs, security vulnerabilities, and code quality issues in the project. Focus on critical issues first.',
    category: 'analysis',
  },
  {
    id: 'performance-audit',
    titleKey: 'agent.templates.performanceAudit',
    titleFallback: 'Performance Audit',
    promptKey: 'agent.templates.performanceAuditPrompt',
    promptFallback: 'Analyze the application for performance bottlenecks including database queries, API response times, memory usage, and frontend rendering.',
    category: 'analysis',
  },
  // Code
  {
    id: 'write-tests',
    titleKey: 'agent.templates.writeTests',
    titleFallback: 'Write Tests',
    promptKey: 'agent.templates.writeTestsPrompt',
    promptFallback: 'Write comprehensive unit tests for the most critical modules. Aim for 80%+ coverage with meaningful test cases.',
    category: 'code',
  },
  {
    id: 'refactor-code',
    titleKey: 'agent.templates.refactorCode',
    titleFallback: 'Refactor Code',
    promptKey: 'agent.templates.refactorCodePrompt',
    promptFallback: 'Identify and refactor code that violates DRY, SOLID principles, or has high complexity. Propose cleaner alternatives.',
    category: 'code',
  },
  {
    id: 'add-feature',
    titleKey: 'agent.templates.addFeature',
    titleFallback: 'Add Feature',
    promptKey: 'agent.templates.addFeaturePrompt',
    promptFallback: 'I want to add a new feature: [describe feature]. Plan the implementation, identify files to modify, and implement it step by step.',
    category: 'code',
  },
  {
    id: 'fix-error',
    titleKey: 'agent.templates.fixError',
    titleFallback: 'Fix Error',
    promptKey: 'agent.templates.fixErrorPrompt',
    promptFallback: 'I\'m getting this error: [paste error]. Diagnose the root cause and fix it.',
    category: 'code',
  },
  // Writing
  {
    id: 'write-docs',
    titleKey: 'agent.templates.writeDocs',
    titleFallback: 'Write Documentation',
    promptKey: 'agent.templates.writeDocsPrompt',
    promptFallback: 'Generate comprehensive documentation for the project including API reference, setup guide, and architecture overview.',
    category: 'writing',
  },
  {
    id: 'write-readme',
    titleKey: 'agent.templates.writeReadme',
    titleFallback: 'Write README',
    promptKey: 'agent.templates.writeReadmePrompt',
    promptFallback: 'Create or improve the project README with sections for: overview, quick start, installation, configuration, usage examples, and contributing.',
    category: 'writing',
  },
  // General
  {
    id: 'explain-code',
    titleKey: 'agent.templates.explainCode',
    titleFallback: 'Explain Code',
    promptKey: 'agent.templates.explainCodePrompt',
    promptFallback: 'Explain how the core system works, walking through the main execution flow from entry point to key outputs.',
    category: 'general',
  },
  {
    id: 'brainstorm',
    titleKey: 'agent.templates.brainstorm',
    titleFallback: 'Brainstorm Ideas',
    promptKey: 'agent.templates.brainstormPrompt',
    promptFallback: 'Help me brainstorm ideas for improving this project. Consider UX improvements, new features, technical debt reduction, and scalability.',
    category: 'general',
  },
];

type SourceTab = 'builtin' | 'custom';

interface PromptTemplateLibraryProps {
  onSelect: (prompt: string) => void;
  onClose: () => void;
  visible: boolean;
}

export const PromptTemplateLibrary = memo<PromptTemplateLibraryProps>(
  ({ onSelect, onClose, visible }) => {
    const { t } = useTranslation();
    const [search, setSearch] = useState('');
    const [activeCategory, setActiveCategory] = useState<TemplateCategory | 'all'>('all');
    const [sourceTab, setSourceTab] = useState<SourceTab>('builtin');
    const [variableTemplate, setVariableTemplate] = useState<{
      title: string;
      content: string;
      variables?: Array<{
        name: string;
        description: string;
        default_value: string;
        required: boolean;
      }>;
    } | null>(null);
    const searchRef = useRef<HTMLInputElement>(null);
    const panelRef = useRef<HTMLDivElement>(null);

    const currentTenant = useCurrentTenant();
    const customTemplates = useTemplateStore((s) => s.templates);
    const customLoading = useTemplateStore((s) => s.loading);
    const { fetchTemplates, deleteTemplate } = useTemplateActions();

    // Fetch custom templates on open
    useEffect(() => {
      if (visible && currentTenant?.id) {
        fetchTemplates(currentTenant.id);
      }
    }, [visible, currentTenant?.id, fetchTemplates]);

    // Focus search on open
    useEffect(() => {
      if (visible) {
        setTimeout(() => searchRef.current?.focus(), 100);
      }
    }, [visible]);

    const handleClose = useCallback(() => {
      setSearch('');
      setActiveCategory('all');
      setSourceTab('builtin');
      onClose();
    }, [onClose]);

    // Close on outside click
    useEffect(() => {
      if (!visible) return;
      const handleClick = (e: MouseEvent) => {
        if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
          handleClose();
        }
      };
      document.addEventListener('mousedown', handleClick);
      return () => document.removeEventListener('mousedown', handleClick);
    }, [visible, handleClose]);

    // Close on Escape
    useEffect(() => {
      if (!visible) return;
      const handleKey = (e: KeyboardEvent) => {
        if (e.key === 'Escape') handleClose();
      };
      window.addEventListener('keydown', handleKey);
      return () => window.removeEventListener('keydown', handleKey);
    }, [visible, handleClose]);

    const filteredBuiltin = useMemo(() => {
      return defaultTemplates.filter((tmpl) => {
        if (activeCategory !== 'all' && tmpl.category !== activeCategory) return false;
        if (!search) return true;
        const q = search.toLowerCase();
        const title = t(tmpl.titleKey, tmpl.titleFallback).toLowerCase();
        const prompt = t(tmpl.promptKey, tmpl.promptFallback).toLowerCase();
        return title.includes(q) || prompt.includes(q);
      });
    }, [search, activeCategory, t]);

    const filteredCustom = useMemo(() => {
      return customTemplates.filter((tmpl) => {
        if (activeCategory !== 'all' && tmpl.category !== activeCategory) return false;
        if (!search) return true;
        const q = search.toLowerCase();
        return tmpl.title.toLowerCase().includes(q) || tmpl.content.toLowerCase().includes(q);
      });
    }, [customTemplates, search, activeCategory]);

    const handleSelectBuiltin = useCallback(
      (tmpl: PromptTemplate) => {
        const prompt = t(tmpl.promptKey, tmpl.promptFallback);
        if (/\{\{\w+\}\}/.test(prompt)) {
          setVariableTemplate({ title: t(tmpl.titleKey, tmpl.titleFallback), content: prompt });
        } else {
          onSelect(prompt);
          handleClose();
        }
      },
      [t, onSelect, handleClose]
    );

    const handleSelectCustom = useCallback(
      (tmpl: PromptTemplateData) => {
        if (/\{\{\w+\}\}/.test(tmpl.content)) {
          setVariableTemplate({
            title: tmpl.title,
            content: tmpl.content,
            variables: tmpl.variables,
          });
        } else {
          onSelect(tmpl.content);
          handleClose();
        }
      },
      [onSelect, handleClose]
    );

    const handleDeleteCustom = useCallback(
      (e: React.MouseEvent, templateId: string) => {
        e.stopPropagation();
        deleteTemplate(templateId);
      },
      [deleteTemplate]
    );

    if (!visible) return null;

    const categories: Array<{ key: TemplateCategory | 'all'; label: string }> = [
      { key: 'all', label: t('agent.templates.all', 'All') },
      { key: 'analysis', label: t('agent.templates.analysis', 'Analysis') },
      { key: 'code', label: t('agent.templates.code', 'Code') },
      { key: 'writing', label: t('agent.templates.writing', 'Writing') },
      { key: 'general', label: t('agent.templates.general', 'General') },
    ];

    return (
      <div
        ref={panelRef}
        className="absolute bottom-full left-0 right-0 mb-2 mx-3 bg-white dark:bg-slate-800 rounded-xl shadow-2xl border border-slate-200 dark:border-slate-700 overflow-hidden z-50 animate-fade-in-up"
        style={{ maxHeight: '420px' }}
      >
        {/* Header */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-100 dark:border-slate-700">
          <Layers size={16} className="text-primary flex-shrink-0" />
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-200 flex-1">
            {t('agent.templates.title', 'Prompt Templates')}
          </span>
          <button
            type="button"
            onClick={handleClose}
            className="p-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400 transition-colors"
          >
            <X size={14} />
          </button>
        </div>

        {/* Search */}
        <div className="px-4 py-2 border-b border-slate-100 dark:border-slate-700">
          <div className="flex items-center gap-2 px-2.5 py-1.5 bg-slate-50 dark:bg-slate-900/50 rounded-lg border border-slate-200 dark:border-slate-700">
            <Search size={14} className="text-slate-400 flex-shrink-0" />
            <input
              ref={searchRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('agent.templates.search', 'Search templates...')}
              className="flex-1 bg-transparent text-sm text-slate-700 dark:text-slate-200 placeholder:text-slate-400 focus:outline-none"
            />
          </div>
        </div>

        {/* Source tabs (Built-in / My Templates) */}
        <div className="flex items-center gap-1 px-4 py-2 border-b border-slate-100 dark:border-slate-700">
          <button
            type="button"
            onClick={() => setSourceTab('builtin')}
            className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
              sourceTab === 'builtin'
                ? 'bg-primary/10 text-primary'
                : 'text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
            }`}
          >
            <Layers size={12} className="inline mr-1" />
            {t('agent.templates.builtIn', 'Built-in')}
          </button>
          <button
            type="button"
            onClick={() => setSourceTab('custom')}
            className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
              sourceTab === 'custom'
                ? 'bg-primary/10 text-primary'
                : 'text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
            }`}
          >
            <User size={12} className="inline mr-1" />
            {t('agent.templates.myTemplates', 'My Templates')}
            {customTemplates.length > 0 && (
              <span className="ml-1 text-[10px] bg-slate-200 dark:bg-slate-600 rounded-full px-1.5">
                {customTemplates.length}
              </span>
            )}
          </button>
        </div>

        {/* Category tabs */}
        <div className="flex items-center gap-1 px-4 py-2 border-b border-slate-100 dark:border-slate-700 overflow-x-auto scrollbar-none">
          {categories.map((cat) => (
            <button
              key={cat.key}
              type="button"
              onClick={() => setActiveCategory(cat.key)}
              className={`
                px-2.5 py-1 rounded-md text-xs font-medium whitespace-nowrap transition-colors
                ${
                  activeCategory === cat.key
                    ? 'bg-primary/10 text-primary'
                    : 'text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
                }
              `}
            >
              {cat.label}
            </button>
          ))}
        </div>

        {/* Template list */}
        <div className="overflow-y-auto" style={{ maxHeight: '280px' }}>
          {sourceTab === 'builtin' ? (
            // Built-in templates
            filteredBuiltin.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-slate-400">
                {t('agent.templates.noResults', 'No templates found')}
              </div>
            ) : (
              <div className="py-1">
                {filteredBuiltin.map((tmpl) => {
                  const cfg = categoryConfig[tmpl.category];
                  return (
                    <button
                      key={tmpl.id}
                      type="button"
                      onClick={() => handleSelectBuiltin(tmpl)}
                      className="w-full text-left px-4 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors group flex items-start gap-3"
                    >
                      <div
                        className={`mt-0.5 w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 ${cfg.colorClass}`}
                      >
                        {cfg.icon}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-slate-700 dark:text-slate-200 flex items-center gap-1">
                          {t(tmpl.titleKey, tmpl.titleFallback)}
                          <ArrowRight
                            size={12}
                            className="opacity-0 group-hover:opacity-100 transition-opacity text-primary"
                          />
                        </div>
                        <div className="text-xs text-slate-400 dark:text-slate-500 mt-0.5 line-clamp-1">
                          {t(tmpl.promptKey, tmpl.promptFallback)}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            )
          ) : (
            // Custom templates
            customLoading ? (
              <div className="px-4 py-8 text-center text-sm text-slate-400">
                <Loader2 size={16} className="inline animate-spin mr-2" />
                Loading...
              </div>
            ) : filteredCustom.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-slate-400">
                {t('agent.templates.noCustom', 'No custom templates yet')}
              </div>
            ) : (
              <div className="py-1">
                {filteredCustom.map((tmpl) => {
                  const cat = (tmpl.category as TemplateCategory) || 'general';
                  const cfg = categoryConfig[cat] || categoryConfig.general;
                  return (
                    <button
                      key={tmpl.id}
                      type="button"
                      onClick={() => handleSelectCustom(tmpl)}
                      className="w-full text-left px-4 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors group flex items-start gap-3"
                    >
                      <div
                        className={`mt-0.5 w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 ${cfg.colorClass}`}
                      >
                        {cfg.icon}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-slate-700 dark:text-slate-200 flex items-center gap-1">
                          {tmpl.title}
                          <ArrowRight
                            size={12}
                            className="opacity-0 group-hover:opacity-100 transition-opacity text-primary"
                          />
                        </div>
                        <div className="text-xs text-slate-400 dark:text-slate-500 mt-0.5 line-clamp-1">
                          {tmpl.content}
                        </div>
                      </div>
                      {!tmpl.is_system && (
                        <button
                          type="button"
                          onClick={(e) => handleDeleteCustom(e, tmpl.id)}
                          className="p-1 rounded-md opacity-0 group-hover:opacity-100 hover:bg-red-50 dark:hover:bg-red-900/20 text-slate-400 hover:text-red-500 transition-all"
                          aria-label="Delete"
                        >
                          <Trash2 size={12} />
                        </button>
                      )}
                    </button>
                  );
                })}
              </div>
            )
          )}
        </div>
        {variableTemplate && (
          <VariableInputModal
            template={variableTemplate}
            visible={!!variableTemplate}
            onClose={() => setVariableTemplate(null)}
            onSubmit={(interpolated) => {
              onSelect(interpolated);
              setVariableTemplate(null);
              handleClose();
            }}
          />
        )}
      </div>
    );
  }
);
PromptTemplateLibrary.displayName = 'PromptTemplateLibrary';

