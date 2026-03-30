import { useEffect } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Tabs, Input, Select, Button, Tag, Space, Card, Rate } from 'antd';
import { Download } from 'lucide-react';

import {
  useGenes,
  useGenomes,
  useGeneMarketLoading,
  useGeneTotal,
  useGenomeTotal,
  useActiveTab,
  useGeneMarketActions,
} from '../../stores/geneMarket';

import type { GeneResponse, GenomeResponse } from '../../services/geneMarketService';

const { Search } = Input;
const { Option } = Select;

export const GeneMarket: FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const genes = useGenes();
  const genomes = useGenomes();
  const loading = useGeneMarketLoading();
  const geneTotal = useGeneTotal();
  const genomeTotal = useGenomeTotal();
  const activeTab = useActiveTab();

  const { listGenes, listGenomes, setActiveTab, installGene, rateGene, clearError, reset } =
    useGeneMarketActions();

  useEffect(() => {
    if (activeTab === 'genes') {
      listGenes();
    } else {
      listGenomes();
    }
  }, [activeTab, listGenes, listGenomes]);

  useEffect(() => {
    return () => {
      clearError();
      reset();
    };
  }, [clearError, reset]);

  const handleTabChange = (key: string) => {
    setActiveTab(key as 'genes' | 'genomes');
  };

  const handlePublishGene = () => {
    navigate('./publish');
  };

  const renderStars = (rating: number | null | undefined, count: number = 0) => {
    const val = rating || 0;
    return (
      <Space size="small" className="items-center">
        <Rate disabled allowHalf value={val} className="text-sm" />
        <span className="text-sm text-slate-500">
          {val.toFixed(1)} ({count} {t('tenant.genes.ratings')})
        </span>
      </Space>
    );
  };

  const getVisibilityBadge = (visibility: string) => {
    const colors: Record<string, string> = {
      public: 'green',
      private: 'red',
      unlisted: 'default',
    };
    return <Tag color={colors[visibility] || 'default'}>{visibility}</Tag>;
  };

  const renderGenesGrid = () => (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
      {genes.map((gene: GeneResponse) => (
        <Card
          key={gene.id}
          className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 hover:border-primary-300 dark:hover:border-primary-600 transition-colors cursor-pointer"
          onClick={() => navigate(`./genes/${gene.id}`)}
          actions={[
            <Button
              key="install"
              type="link"
              onClick={(e) => {
                e.stopPropagation();
                installGene('default-instance', { gene_id: gene.id });
              }}
            >
              {t('tenant.genes.actions.install')}
            </Button>,
            <Button
              key="rate"
              type="link"
              onClick={(e) => {
                e.stopPropagation();
                rateGene(gene.id, { score: 5, comment: '' });
              }}
            >
              {t('tenant.genes.actions.rate')}
            </Button>,
          ]}
        >
          <div className="flex justify-between items-start mb-2">
            <h3 className="text-lg font-semibold truncate">{gene.name}</h3>
            {getVisibilityBadge(gene.visibility)}
          </div>

          <div className="mb-2">
            <Tag color="blue">{gene.category}</Tag>
            <span className="text-slate-500 text-sm ml-2">v{gene.version}</span>
          </div>

          <p className="text-slate-600 dark:text-slate-400 text-sm mb-4 line-clamp-2 min-h-10">
            {gene.description}
          </p>

          <div className="mb-4">
            {gene.tags?.slice(0, 3).map((tag: string) => (
              <Tag key={tag} className="mr-1 mb-1">
                {tag}
              </Tag>
            ))}
            {(gene.tags?.length || 0) > 3 && <Tag>...</Tag>}
          </div>

          <div className="flex justify-between items-center text-sm text-slate-500">
            <div>
              <Download size={14} className="mr-1 align-text-bottom" />
              {gene.download_count}
            </div>
            {renderStars(gene.avg_rating, 0)}
          </div>
        </Card>
      ))}
    </div>
  );

  const renderGenomesGrid = () => (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
      {genomes.map((genome: GenomeResponse) => (
        <Card
          key={genome.id}
          className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 hover:border-primary-300 dark:hover:border-primary-600 transition-colors cursor-pointer"
          onClick={() => navigate(`./genomes/${genome.id}`)}
        >
          <div className="flex justify-between items-start mb-2">
            <h3 className="text-lg font-semibold truncate">{genome.name}</h3>
            {getVisibilityBadge(genome.visibility)}
          </div>

          <p className="text-slate-600 dark:text-slate-400 text-sm mb-4 line-clamp-2 min-h-10">
            {genome.description}
          </p>

          <div className="mb-4 flex gap-2">
            <Tag color="purple">
              {genome.gene_ids?.length || 0} {t('tenant.genes.genesCount')}
            </Tag>
          </div>

          <div className="flex justify-end items-center text-sm text-slate-500">
            {renderStars(genome.avg_rating, 0)}
          </div>
        </Card>
      ))}
    </div>
  );

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-semibold">{t('tenant.genes.title')}</h1>
          <p className="text-slate-500">{t('tenant.genes.subtitle')}</p>
        </div>
        <Button type="primary" onClick={handlePublishGene}>
          {t('tenant.genes.publishButton')}
        </Button>
      </div>

      <div className="flex justify-between items-center gap-4 bg-white dark:bg-slate-800 p-4 rounded-lg border border-slate-200 dark:border-slate-700">
        <div className="flex-1">
          <Search
            placeholder={t('tenant.genes.searchPlaceholder')}
            allowClear
            className="max-w-md"
          />
        </div>
        <Space>
          <Select defaultValue="all" style={{ width: 120 }}>
            <Option value="all">{t('tenant.genes.filters.allCategories')}</Option>
            <Option value="ai">{t('tenant.genes.filters.catAi')}</Option>
            <Option value="tool">{t('tenant.genes.filters.catTool')}</Option>
          </Select>
          <Select defaultValue="all" style={{ width: 120 }}>
            <Option value="all">{t('tenant.genes.filters.allVisibility')}</Option>
            <Option value="public">{t('tenant.genes.filters.visPublic')}</Option>
            <Option value="private">{t('tenant.genes.filters.visPrivate')}</Option>
          </Select>
        </Space>
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
        items={[
          {
            key: 'genes',
            label: `${t('tenant.genes.tabs.genes')} (${geneTotal})`,
            children: loading ? <div>{t('tenant.genes.loading')}</div> : renderGenesGrid(),
          },
          {
            key: 'genomes',
            label: `${t('tenant.genes.tabs.genomes')} (${genomeTotal})`,
            children: loading ? <div>{t('tenant.genes.loading')}</div> : renderGenomesGrid(),
          },
        ]}
      />
    </div>
  );
};
