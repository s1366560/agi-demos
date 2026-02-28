/**
 * TemplateMarketplace - Page for browsing and installing SubAgent templates.
 * Lists templates with search, category filtering, and install actions.
 */

import React, { useEffect, useState, useMemo, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { Input, Tag, Empty, Spin, App } from 'antd';
import { Search, Download, Star, Package, Shield, Bot } from 'lucide-react';

import { subagentTemplateService } from '../../services/subagentTemplateService';

import type { SubAgentTemplateListItem } from '../../services/subagentTemplateService';

const CATEGORY_COLORS: Record<string, string> = {
  research: 'blue',
  coding: 'green',
  writing: 'purple',
  analysis: 'orange',
  general: 'default',
};

export const TemplateMarketplace: React.FC = () => {
  const { t } = useTranslation();
  const { message } = App.useApp();

  const [templates, setTemplates] = useState<SubAgentTemplateListItem[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [installing, setInstalling] = useState<Set<string>>(new Set());

  // Load templates and categories
  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [listRes, cats] = await Promise.all([
          subagentTemplateService.list({
            category: selectedCategory || undefined,
            search: search || undefined,
          }),
          subagentTemplateService.getCategories(),
        ]);
        setTemplates(listRes.templates || []);
        setCategories(cats);
      } catch {
        message.error(t('agent.templates.loadError', 'Failed to load templates'));
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [selectedCategory, search, message, t]);

  const handleInstall = useCallback(
    async (templateId: string) => {
      setInstalling((prev) => new Set(prev).add(templateId));
      try {
        const result = await subagentTemplateService.install(templateId, 'default');
        message.success(
          t('agent.templates.installed', 'Installed SubAgent: {{name}}', {
            name: result.name,
          })
        );
      } catch {
        message.error(t('agent.templates.installError', 'Failed to install template'));
      } finally {
        setInstalling((prev) => {
          const next = new Set(prev);
          next.delete(templateId);
          return next;
        });
      }
    },
    [message, t]
  );

  const handleSeed = useCallback(async () => {
    try {
      const result = await subagentTemplateService.seed();
      message.success(
        t('agent.templates.seeded', 'Seeded {{count}} templates', {
          count: result.seeded,
        })
      );
      // Reload
      const listRes = await subagentTemplateService.list();
      setTemplates(listRes.templates || []);
    } catch {
      message.error(t('agent.templates.seedError', 'Failed to seed templates'));
    }
  }, [message, t]);

  const filteredTemplates = useMemo(() => {
    if (!search) return templates;
    const q = search.toLowerCase();
    return templates.filter(
      (tpl) =>
        tpl.name.toLowerCase().includes(q) ||
        tpl.display_name.toLowerCase().includes(q) ||
        tpl.description.toLowerCase().includes(q) ||
        tpl.tags.some((tag) => tag.toLowerCase().includes(q))
    );
  }, [templates, search]);

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-slate-800 dark:text-slate-200 flex items-center gap-2">
            <Package size={22} />
            {t('agent.templates.marketplace', 'Template Marketplace')}
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            {t(
              'agent.templates.marketplaceDesc',
              'Browse and install SubAgent templates to extend your agent capabilities.'
            )}
          </p>
        </div>
        <button
          onClick={handleSeed}
          className="px-3 py-1.5 text-xs rounded-md border border-slate-300 dark:border-slate-600
            text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
        >
          {t('agent.templates.seedBuiltin', 'Seed Built-in')}
        </button>
      </div>

      {/* Search + Category Filter */}
      <div className="flex items-center gap-3 mb-5">
        <Input
          prefix={<Search size={14} className="text-slate-400" />}
          placeholder={t('agent.templates.search', 'Search templates...')}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
          className="max-w-sm"
          allowClear
        />
        <div className="flex gap-1.5 flex-wrap">
          <Tag
            {...(selectedCategory === '' ? { color: 'blue' as const } : {})}
            className="cursor-pointer"
            onClick={() => {
              setSelectedCategory('');
            }}
          >
            {t('agent.templates.all', 'All')}
          </Tag>
          {categories.map((cat) => (
            <Tag
              key={cat}
              {...(selectedCategory === cat ? { color: CATEGORY_COLORS[cat] || 'blue' } : {})}
              className="cursor-pointer"
              onClick={() => {
                setSelectedCategory(cat);
              }}
            >
              {cat}
            </Tag>
          ))}
        </div>
      </div>

      {/* Template Grid */}
      {loading ? (
        <div className="flex justify-center py-20">
          <Spin size="large" />
        </div>
      ) : filteredTemplates.length === 0 ? (
        <Empty
          description={t('agent.templates.noResults', 'No templates found')}
          className="py-20"
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredTemplates.map((tpl) => (
            <div
              key={tpl.id}
              className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800
                p-4 hover:shadow-md dark:hover:shadow-slate-900/40 transition-shadow"
            >
              {/* Card Header */}
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Bot size={18} className="text-blue-500 shrink-0" />
                  <div>
                    <h3 className="text-sm font-medium text-slate-800 dark:text-slate-200 truncate max-w-[180px]">
                      {tpl.display_name || tpl.name}
                    </h3>
                    <span className="text-[10px] text-slate-400">v{tpl.version}</span>
                  </div>
                </div>
                {tpl.is_builtin && (
                  <span title="Built-in">
                    <Shield size={14} className="text-amber-500 shrink-0" />
                  </span>
                )}
              </div>

              {/* Description */}
              <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2 mb-3 min-h-[32px]">
                {tpl.description || 'No description'}
              </p>

              {/* Tags */}
              <div className="flex flex-wrap gap-1 mb-3">
                <Tag color={CATEGORY_COLORS[tpl.category] || 'default'} className="text-[10px]">
                  {tpl.category}
                </Tag>
                {tpl.tags.slice(0, 3).map((tag) => (
                  <Tag key={tag} className="text-[10px]">
                    {tag}
                  </Tag>
                ))}
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between pt-2 border-t border-slate-100 dark:border-slate-700/50">
                <div className="flex items-center gap-3 text-[10px] text-slate-400">
                  <span className="flex items-center gap-0.5">
                    <Download size={10} />
                    {tpl.install_count}
                  </span>
                  {tpl.rating > 0 && (
                    <span className="flex items-center gap-0.5">
                      <Star size={10} />
                      {tpl.rating.toFixed(1)}
                    </span>
                  )}
                  {tpl.author && <span>{tpl.author}</span>}
                </div>
                <button
                  onClick={() => handleInstall(tpl.id)}
                  disabled={installing.has(tpl.id)}
                  className="px-2.5 py-1 text-xs rounded-md bg-blue-500 hover:bg-blue-600
                    text-white disabled:opacity-50 transition-colors flex items-center gap-1"
                >
                  {installing.has(tpl.id) ? (
                    <Spin size="small" />
                  ) : (
                    <>
                      <Download size={12} />
                      {t('agent.templates.install', 'Install')}
                    </>
                  )}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
