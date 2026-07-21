import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Alert, Button, Empty, Input, Modal, Pagination, Spin, Tag, Typography } from 'antd';
import { Search } from 'lucide-react';

import { geneMarketService, type GeneResponse } from '@/services/geneMarketService';

import { marketplaceGeneToPayload } from './marketplaceMapper';
import { getCategoryColor } from './utils';

import type { GenePayload } from './GeneEditorModal';

export interface GeneImportModalProps {
  open: boolean;
  tenantId: string;
  onCancel: () => void;
  /** Called when the user picks a marketplace gene. Receives a draft to seed the editor. */
  onSelect: (draft: Partial<GenePayload>, source: GeneResponse) => void;
}

const PAGE_SIZE = 10;

export const GeneImportModal: React.FC<GeneImportModalProps> = ({
  open,
  tenantId,
  onCancel,
  onSelect,
}) => {
  const { t, i18n } = useTranslation();

  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<GeneResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const compactNumber = useMemo(
    () => new Intl.NumberFormat(i18n.language, { notation: 'compact' }),
    [i18n.language]
  );

  const fetchPage = useCallback(
    async (nextPage: number, query: string) => {
      setLoading(true);
      setError(null);
      try {
        const params: {
          page: number;
          page_size: number;
          search?: string;
          is_published?: boolean;
          tenant_id?: string;
        } = {
          page: nextPage,
          page_size: PAGE_SIZE,
          is_published: true,
          tenant_id: tenantId,
        };
        if (query.trim() !== '') params.search = query.trim();
        const data = await geneMarketService.listGenes(params);
        setItems(data.genes);
        setTotal(data.total);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : t('workspaceDetail.genes.marketplaceLoadFailed', 'Failed to load marketplace')
        );
        setItems([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [tenantId, t]
  );

  useEffect(() => {
    if (!open) return undefined;
    const timer = setTimeout(() => {
      setPage(1);
      void fetchPage(1, search);
    }, 250);
    return () => {
      clearTimeout(timer);
    };
  }, [open, fetchPage, search]);

  const handleSearch = useCallback(() => {
    setPage(1);
    void fetchPage(1, search);
  }, [fetchPage, search]);

  const handlePageChange = useCallback(
    (next: number) => {
      setPage(next);
      void fetchPage(next, search);
    },
    [fetchPage, search]
  );

  const pagination = useMemo(() => {
    if (total <= PAGE_SIZE) return null;
    return (
      <div className="mt-3 flex justify-end">
        <Pagination
          current={page}
          pageSize={PAGE_SIZE}
          total={total}
          showSizeChanger={false}
          onChange={handlePageChange}
        />
      </div>
    );
  }, [handlePageChange, page, total]);

  return (
    <Modal
      open={open}
      title={t('workspaceDetail.genes.importFromMarketplace', 'Import from Gene Marketplace')}
      width={720}
      footer={null}
      onCancel={onCancel}
      destroyOnHidden
    >
      <div className="space-y-3">
        <Input
          allowClear
          aria-label={t(
            'workspaceDetail.genes.marketplaceSearchPlaceholder',
            'Search marketplace genes…'
          )}
          placeholder={t(
            'workspaceDetail.genes.marketplaceSearchPlaceholder',
            'Search marketplace genes…'
          )}
          prefix={<Search size={14} />}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
          onPressEnter={handleSearch}
          onBlur={handleSearch}
        />

        {error && (
          <Alert
            type="error"
            showIcon
            title={error}
            action={
              <Button
                size="small"
                onClick={() => {
                  void fetchPage(page, search);
                }}
              >
                {t('common.retry', 'Retry')}
              </Button>
            }
          />
        )}

        <div className="min-h-[240px] max-h-[420px] overflow-y-auto rounded border border-slate-200 dark:border-slate-700">
          {loading ? (
            <div className="flex h-40 items-center justify-center" role="status">
              <Spin />
            </div>
          ) : items.length === 0 ? (
            <div className="flex h-40 items-center justify-center">
              <Empty
                description={t(
                  'workspaceDetail.genes.noMarketplaceResults',
                  'No marketplace genes found'
                )}
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            </div>
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-700">
              {items.map((gene) => (
                <li key={gene.id}>
                  <button
                    type="button"
                    className="w-full px-4 py-3 text-left transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/50 dark:hover:bg-slate-800"
                    onClick={() => {
                      onSelect(marketplaceGeneToPayload(gene), gene);
                    }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Typography.Text strong>{gene.name}</Typography.Text>
                          {gene.category && (
                            <Tag
                              color={getCategoryColor(gene.category)}
                              className="m-0 border-transparent text-xs"
                            >
                              {gene.category}
                            </Tag>
                          )}
                          <Tag color="default" className="m-0 border-transparent text-xs">
                            v{gene.version}
                          </Tag>
                        </div>
                        {gene.description && (
                          <Typography.Paragraph
                            className="m-0 mt-1 text-xs text-slate-500 dark:text-slate-400"
                            ellipsis={{ rows: 2, tooltip: gene.description }}
                          >
                            {gene.description}
                          </Typography.Paragraph>
                        )}
                      </div>
                      <div className="shrink-0 text-xs text-slate-400 dark:text-slate-500">
                        <span className="tabular-nums">
                          ↓ {compactNumber.format(gene.install_count)}
                        </span>
                      </div>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {pagination}
      </div>
    </Modal>
  );
};
