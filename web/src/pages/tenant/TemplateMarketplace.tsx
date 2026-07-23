/**
 * TemplateMarketplace - Page for browsing and installing SubAgent templates.
 * Lists templates with search, category filtering, and install actions.
 */

import React, { useEffect, useState, useCallback, useRef } from 'react';

import { useTranslation } from 'react-i18next';

import { Input, Tag, Empty, Spin, App, Pagination, Tooltip } from 'antd';
import { Search, Download, Star, Package, Shield, Bot, RefreshCw } from 'lucide-react';

import { SkeletonLoader } from '@/components/common/SkeletonLoader';
import { SubAgentTemplateDetailDrawer } from '@/components/marketplace/SubAgentTemplateDetailDrawer';

import { useDebounce } from '../../hooks/useDebounce';
import { subagentTemplateService } from '../../services/subagentTemplateService';

import type { SubAgentTemplateListItem } from '../../services/subagentTemplateService';

const PAGE_SIZE = 12;

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
  const [loadError, setLoadError] = useState(false);
  const [retryToken, setRetryToken] = useState(0);
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [detailTemplateId, setDetailTemplateId] = useState<string | null>(null);
  const [installing, setInstalling] = useState<Set<string>>(new Set());
  const [seeding, setSeeding] = useState(false);
  const loadRequestSeqRef = useRef(0);
  const debouncedSearch = useDebounce(search, 300);

  // Load templates and categories (server-side search/filter/pagination)
  useEffect(() => {
    const requestSeq = loadRequestSeqRef.current + 1;
    loadRequestSeqRef.current = requestSeq;

    const load = async () => {
      setLoading(true);
      try {
        const [listRes, cats] = await Promise.all([
          subagentTemplateService.list({
            category: selectedCategory || undefined,
            search: debouncedSearch || undefined,
            page,
            page_size: PAGE_SIZE,
          }),
          subagentTemplateService.getCategories(),
        ]);
        if (loadRequestSeqRef.current !== requestSeq) {
          return;
        }

        setTemplates(listRes.templates);
        setTotal(listRes.total);
        setCategories(cats);
        setLoadError(false);
      } catch {
        if (loadRequestSeqRef.current === requestSeq) {
          setLoadError(true);
          message.error(t('agent.templates.loadError', 'Failed to load templates'));
        }
      } finally {
        if (loadRequestSeqRef.current === requestSeq) {
          setLoading(false);
        }
      }
    };
    void load();

    return () => {
      if (loadRequestSeqRef.current === requestSeq) {
        loadRequestSeqRef.current += 1;
      }
    };
  }, [selectedCategory, debouncedSearch, page, retryToken, message, t]);

  const handleInstall = useCallback(
    async (templateId: string) => {
      setInstalling((prev) => new Set(prev).add(templateId));
      try {
        const result = await subagentTemplateService.install(templateId);
        message.success(
          t('agent.templates.installed', 'Installed SubAgent: {{name}}', {
            name: result.display_name || result.name,
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
    if (seeding) return;
    setSeeding(true);
    try {
      const result = await subagentTemplateService.seed();
      message.success(
        t('agent.templates.seeded', 'Seeded {{count}} templates', {
          count: result.seeded,
        })
      );
      // Reload through the normal loader so current category/search filters are kept
      setPage(1);
      setRetryToken((token) => token + 1);
    } catch {
      message.error(t('agent.templates.seedError', 'Failed to seed templates'));
    } finally {
      setSeeding(false);
    }
  }, [message, seeding, t]);

  const handleCategoryChange = useCallback((category: string) => {
    setSelectedCategory(category);
    setPage(1);
  }, []);

  const handleSearchChange = useCallback((value: string) => {
    setSearch(value);
    setPage(1);
  }, []);

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
          type="button"
          onClick={() => {
            void handleSeed();
          }}
          disabled={seeding}
          className="px-3 py-1.5 text-xs rounded-md border border-slate-300 dark:border-slate-600
            text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {seeding
            ? t('agent.templates.seeding', 'Seeding…')
            : t('agent.templates.seedBuiltin', 'Seed Built-in')}
        </button>
      </div>

      {/* Search + Category Filter */}
      <div className="flex items-center gap-3 mb-5">
        <Input
          prefix={<Search size={14} className="text-slate-400" />}
          placeholder={t('agent.templates.search', 'Search templates…')}
          aria-label={t('agent.templates.search', 'Search templates…')}
          value={search}
          onChange={(e) => {
            handleSearchChange(e.target.value);
          }}
          className="max-w-sm"
          allowClear
        />
        <div
          className="flex gap-1.5 flex-wrap"
          role="group"
          aria-label={t('agent.templates.categoryFilter', 'Category filter')}
        >
          <button
            type="button"
            aria-pressed={selectedCategory === ''}
            onClick={() => {
              handleCategoryChange('');
            }}
            className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 ${
              selectedCategory === ''
                ? 'border-blue-300 bg-blue-50 text-blue-600 dark:border-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
                : 'border-slate-200 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-700'
            }`}
          >
            {t('agent.templates.all', 'All')}
          </button>
          {categories.map((cat) => (
            <button
              key={cat}
              type="button"
              aria-pressed={selectedCategory === cat}
              onClick={() => {
                handleCategoryChange(cat);
              }}
              className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 ${
                selectedCategory === cat
                  ? 'border-blue-300 bg-blue-50 text-blue-600 dark:border-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
                  : 'border-slate-200 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-700'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Template Grid */}
      {loading ? (
        <SkeletonLoader type="card" count={6} />
      ) : loadError ? (
        <div className="flex flex-col items-center gap-3 py-20">
          <p className="text-sm text-slate-500 dark:text-slate-400" role="alert">
            {t('agent.templates.loadError', 'Failed to load templates')}
          </p>
          <button
            type="button"
            onClick={() => {
              setRetryToken((token) => token + 1);
            }}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 dark:border-slate-600 dark:text-slate-400 dark:hover:bg-slate-700"
          >
            <RefreshCw size={12} />
            {t('common.retry')}
          </button>
        </div>
      ) : templates.length === 0 ? (
        <Empty description={t('agent.templates.noResults', 'No templates found')} className="py-20">
          <button
            type="button"
            onClick={() => {
              void handleSeed();
            }}
            disabled={seeding}
            className="px-3 py-1.5 text-xs rounded-md bg-blue-500 hover:bg-blue-600 text-white transition-colors
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {seeding
              ? t('agent.templates.seeding', 'Seeding…')
              : t('agent.templates.seedBuiltin', 'Seed Built-in')}
          </button>
        </Empty>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {templates.map((tpl) => (
            <div
              key={tpl.id}
              className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800
                p-4 hover:shadow-md dark:hover:shadow-slate-900/40 transition-shadow"
            >
              {/* Card Header */}
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2 min-w-0">
                  <Bot size={18} className="text-blue-500 shrink-0" />
                  <div className="min-w-0">
                    <h3 className="text-sm font-medium text-slate-800 dark:text-slate-200 truncate max-w-[180px]">
                      <button
                        type="button"
                        onClick={() => {
                          setDetailTemplateId(tpl.id);
                        }}
                        className="hover:text-blue-600 dark:hover:text-blue-400 transition-colors
                          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 rounded-sm"
                        aria-label={t('agent.templates.viewDetails', 'View details of {{name}}', {
                          name: tpl.display_name || tpl.name,
                        })}
                      >
                        {tpl.display_name || tpl.name}
                      </button>
                    </h3>
                    <span className="text-2xs text-slate-400">v{tpl.version}</span>
                  </div>
                </div>
                {tpl.is_builtin && (
                  <Tooltip title={t('agent.templates.builtIn', { defaultValue: 'Built-in' })}>
                    <Shield
                      size={14}
                      className="text-amber-500 shrink-0"
                      aria-label={t('agent.templates.builtIn', { defaultValue: 'Built-in' })}
                    />
                  </Tooltip>
                )}
              </div>

              {/* Description */}
              <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2 mb-3 min-h-8">
                {tpl.description ||
                  t('agent.templates.noDescription', { defaultValue: 'No description' })}
              </p>

              {/* Tags */}
              <div className="flex flex-wrap gap-1 mb-3">
                <Tag color={CATEGORY_COLORS[tpl.category] || 'default'} className="text-2xs">
                  {tpl.category}
                </Tag>
                {tpl.tags.slice(0, 3).map((tag) => (
                  <Tag key={tag} className="text-2xs">
                    {tag}
                  </Tag>
                ))}
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between pt-2 border-t border-slate-100 dark:border-slate-700/50">
                <div className="flex items-center gap-3 text-2xs text-slate-400">
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
                  type="button"
                  onClick={() => {
                    void handleInstall(tpl.id);
                  }}
                  disabled={installing.has(tpl.id)}
                  className="px-2.5 py-1 text-xs rounded-md bg-blue-500 hover:bg-blue-600
                    text-white disabled:opacity-50 transition-colors flex items-center gap-1
                    focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60"
                >
                  {installing.has(tpl.id) ? (
                    <>
                      <Spin size="small" />
                      {t('agent.templates.installing', 'Installing…')}
                    </>
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

      {total > PAGE_SIZE && !loading && !loadError ? (
        <div className="flex justify-end mt-6">
          <Pagination
            current={page}
            pageSize={PAGE_SIZE}
            total={total}
            showSizeChanger={false}
            onChange={(nextPage) => {
              setPage(nextPage);
            }}
          />
        </div>
      ) : null}

      <SubAgentTemplateDetailDrawer
        templateId={detailTemplateId}
        onClose={() => {
          setDetailTemplateId(null);
        }}
        onInstall={(templateId) => {
          void handleInstall(templateId);
        }}
        installing={detailTemplateId !== null && installing.has(detailTemplateId)}
      />
    </div>
  );
};
