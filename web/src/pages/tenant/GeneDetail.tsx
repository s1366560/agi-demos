import { useEffect, useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';

import {
  Button,
  Badge,
  Card,
  Empty,
  Tag,
  Modal,
  Form,
  Input,
  Rate,
  Typography,
  Space,
  message,
  Avatar,
  Pagination,
  Collapse,
} from 'antd';
import {
  ArrowLeft,
  Download,
  Edit2,
  GitCommit,
  Star,
  Tag as TagIcon,
  User,
  Trash2,
} from 'lucide-react';

import { formatDateOnly, formatDateTime } from '@/utils/date';

import { SkeletonLoader } from '@/components/common/SkeletonLoader';
import { InstallEntityModal } from '@/components/marketplace/InstallEntityModal';
import { PublishToggleButton } from '@/components/marketplace/PublishToggleButton';
import { useDeleteEntityConfirm } from '@/components/marketplace/useDeleteEntityConfirm';

import { useAuthStore } from '../../stores/auth';
import {
  useCurrentGene,
  useGeneReviews,
  useGeneReviewsTotal,
  useGeneReviewsLoading,
  useEvolutionEvents,
  useGeneMarketLoading,
  useGeneMarketActions,
} from '../../stores/geneMarket';
import { useCurrentTenant } from '../../stores/tenant';

import { visibilityLabel, visibilityTagColor } from './geneVisibility';
import { EvolutionTimeline } from './utils/EvolutionTimeline';
import { GeneFormFields } from './utils/GeneFormFields';
import {
  isFormValidationError,
  normalizeNullableText,
  showGeneActionError,
  splitCsv,
} from './utils/geneFormUtils';

import type { ContentVisibilityValue, GeneUpdate } from '../../services/geneMarketService';

const { Title, Text, Paragraph } = Typography;

interface ReviewFormValues {
  rating: number;
  content: string;
}

interface EditGeneFormValues {
  name: string;
  slug: string;
  category?: string;
  version: string;
  short_description?: string;
  description?: string;
  visibility?: ContentVisibilityValue;
  tags?: string;
}

export const GeneDetail: FC = () => {
  const { tenantId: routeTenantId, geneId } = useParams<{ tenantId?: string; geneId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const shouldOpenInstallModal = searchParams.get('install') === '1';
  const shouldOpenRateModal = searchParams.get('rate') === '1';
  const { t } = useTranslation();
  const currentTenant = useCurrentTenant();
  const tenantId = routeTenantId ?? currentTenant?.id ?? null;
  const currentUserId = useAuthStore((s) => s.user?.id);

  const currentGene = useCurrentGene();
  const evolutionEvents = useEvolutionEvents();
  const isLoading = useGeneMarketLoading();
  const reviews = useGeneReviews();
  const reviewsTotal = useGeneReviewsTotal();
  const reviewsLoading = useGeneReviewsLoading();
  const {
    getGene,
    installGene,
    listGeneEvolutionEvents,
    clearError,
    reset,
    fetchGeneReviews,
    createGeneReview,
    deleteGeneReview,
    publishGene,
    unpublishGene,
    deleteGene,
    updateGene,
  } = useGeneMarketActions();

  const [isInstallModalVisible, setIsInstallModalVisible] = useState(shouldOpenInstallModal);
  const [isEditModalVisible, setIsEditModalVisible] = useState(false);
  const [isEditSubmitting, setIsEditSubmitting] = useState(false);
  const [isReviewSubmitting, setIsReviewSubmitting] = useState(false);
  const [editForm] = Form.useForm<EditGeneFormValues>();
  // The ?rate=1 deep link from marketplace cards converges on the single
  // review flow below (the standalone header Rate action was removed).
  const [isReviewModalVisible, setIsReviewModalVisible] = useState(shouldOpenRateModal);
  const [reviewForm] = Form.useForm<ReviewFormValues>();
  const [reviewPage, setReviewPage] = useState(1);
  const reviewPageSize = 5;

  const { isDeleting, confirmDelete } = useDeleteEntityConfirm({
    entityKind: 'gene',
    deleteEntity: deleteGene,
    onDeleted: () => {
      void navigate(-1);
    },
  });

  useEffect(() => {
    if (!geneId || !tenantId) {
      return;
    }

    const options = { tenant_id: tenantId };
    void Promise.all([
      getGene(geneId, options).catch(() => {
        message.error(t('tenant.genes.fetchError'));
      }),
      listGeneEvolutionEvents(geneId, options).catch(() => undefined),
    ]);

    return () => {
      clearError();
      reset();
    };
  }, [geneId, getGene, listGeneEvolutionEvents, clearError, reset, t, tenantId]);

  useEffect(() => {
    if (!geneId || !tenantId) {
      return;
    }

    fetchGeneReviews(geneId, reviewPage, reviewPageSize, { tenant_id: tenantId }).catch(
      () => undefined
    );
  }, [fetchGeneReviews, geneId, reviewPage, reviewPageSize, tenantId]);

  useEffect(() => {
    if (!shouldOpenInstallModal && !shouldOpenRateModal) {
      return;
    }
    const nextParams = new URLSearchParams(searchParams);
    if (shouldOpenInstallModal) {
      nextParams.delete('install');
    }
    if (shouldOpenRateModal) {
      nextParams.delete('rate');
    }
    setSearchParams(nextParams, { replace: true });
  }, [searchParams, setSearchParams, shouldOpenInstallModal, shouldOpenRateModal]);

  const handleInstall = async (instanceId: string, config: Record<string, unknown>) => {
    await installGene(
      instanceId,
      {
        gene_id: geneId ?? '',
        config,
      },
      tenantId ? { tenant_id: tenantId } : undefined
    );
  };

  const handleReviewSubmit = async () => {
    let values: ReviewFormValues;
    try {
      values = await reviewForm.validateFields();
    } catch {
      return;
    }
    if (!geneId || !tenantId) {
      return;
    }
    setIsReviewSubmitting(true);
    try {
      const options = { tenant_id: tenantId };
      await createGeneReview(
        geneId,
        {
          rating: values.rating,
          content: values.content,
        },
        options
      );
      setReviewPage(1);
      await fetchGeneReviews(geneId, 1, reviewPageSize, options);
      message.success(t('gene.reviewSubmitSuccess'));
      setIsReviewModalVisible(false);
      reviewForm.resetFields();
    } catch {
      showGeneActionError(t('gene.reviewSubmitError'));
    } finally {
      setIsReviewSubmitting(false);
    }
  };

  const openEditModal = () => {
    if (!currentGene) {
      return;
    }
    editForm.setFieldsValue({
      name: currentGene.name,
      slug: currentGene.slug,
      category: currentGene.category ?? '',
      version: currentGene.version,
      short_description: currentGene.short_description ?? '',
      description: currentGene.description ?? '',
      visibility: currentGene.visibility,
      tags: currentGene.tags.join(', '),
    });
    setIsEditModalVisible(true);
  };

  const handleEditSubmit = async () => {
    if (!geneId || !tenantId) {
      return;
    }

    try {
      const values = await editForm.validateFields();
      const payload: GeneUpdate = {
        name: values.name.trim(),
        slug: values.slug.trim(),
        category: normalizeNullableText(values.category),
        version: values.version.trim(),
        short_description: normalizeNullableText(values.short_description),
        description: normalizeNullableText(values.description),
        visibility: values.visibility ?? 'public',
        tags: splitCsv(values.tags),
      };
      setIsEditSubmitting(true);
      await updateGene(geneId, payload, { tenant_id: tenantId });
      message.success(t('tenant.genes.updateSuccess', 'Gene updated successfully'));
      setIsEditModalVisible(false);
      editForm.resetFields();
    } catch (error) {
      if (!isFormValidationError(error)) {
        showGeneActionError(t('tenant.genes.updateError', 'Failed to update gene'));
      }
    } finally {
      setIsEditSubmitting(false);
    }
  };

  const handleDeleteReview = (reviewId: string) => {
    Modal.confirm({
      title: t('gene.deleteReview'),
      content: t('gene.deleteReviewConfirm'),
      okText: t('common.yes'),
      cancelText: t('common.no'),
      onOk: async () => {
        if (geneId && tenantId) {
          try {
            const options = { tenant_id: tenantId };
            await deleteGeneReview(geneId, reviewId, options);
            const nextPage = reviews.length === 1 && reviewPage > 1 ? reviewPage - 1 : reviewPage;
            setReviewPage(nextPage);
            await fetchGeneReviews(geneId, nextPage, reviewPageSize, options);
            message.success(t('gene.reviewDeleteSuccess'));
          } catch {
            showGeneActionError(t('gene.reviewDeleteError'));
          }
        }
      },
    });
  };

  if (isLoading && !currentGene) {
    return (
      <div className="max-w-full mx-auto w-full">
        <SkeletonLoader type="form" />
      </div>
    );
  }

  if (!currentGene) {
    return (
      <div className="text-center mt-12">
        <Title level={4}>{t('tenant.genes.notFound')}</Title>
        <Button
          onClick={() => {
            void navigate(-1);
          }}
          icon={<ArrowLeft className="w-4 h-4" />}
        >
          {t('tenant.genes.back')}
        </Button>
      </div>
    );
  }

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <Space orientation="vertical" size="small">
          <Button
            type="text"
            icon={<ArrowLeft className="w-4 h-4" />}
            onClick={() => {
              void navigate(-1);
            }}
            className="pl-0"
          >
            {t('tenant.genes.back')}
          </Button>
          <Space align="center" size="middle" wrap className="mt-2">
            <Title level={2} className="!mb-0">
              {currentGene.name}
            </Title>
            <Badge count={`v${currentGene.version}`} color="blue" />
            {currentGene.category && <Tag color="purple">{currentGene.category}</Tag>}
            <Tag color={currentGene.is_published ? 'green' : 'default'}>
              {currentGene.is_published
                ? t('tenant.genes.statusPublished', 'Published')
                : t('tenant.genes.statusDraft', 'Draft')}
            </Tag>
            <Tag color={visibilityTagColor(currentGene.visibility)}>
              {visibilityLabel(currentGene.visibility, t)}
            </Tag>
          </Space>
          {currentGene.updated_at ? (
            <Text type="secondary" className="text-xs">
              {t('tenant.genes.lastUpdated', 'Last updated {{time}}', {
                time: formatDateTime(currentGene.updated_at),
              })}
            </Text>
          ) : null}
        </Space>

        <Space wrap>
          <Button onClick={openEditModal} icon={<Edit2 className="w-4 h-4" />}>
            {t('tenant.genes.editAction', 'Edit')}
          </Button>
          <PublishToggleButton
            entityKind="gene"
            entityId={geneId}
            tenantId={tenantId}
            entityName={currentGene.name}
            isPublished={currentGene.is_published}
            actions={{ publish: publishGene, unpublish: unpublishGene }}
          />
          <Button
            type="primary"
            onClick={() => {
              setIsInstallModalVisible(true);
            }}
            icon={<Download className="w-4 h-4" />}
          >
            {t('tenant.genes.installAction')}
          </Button>
          <Button
            danger
            loading={isDeleting}
            onClick={() => {
              confirmDelete({ entityId: geneId, tenantId, entityName: currentGene.name });
            }}
            icon={<Trash2 className="w-4 h-4" />}
          >
            {t('tenant.genes.deleteAction', 'Delete')}
          </Button>
        </Space>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
        <Card
          size="small"
          className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700"
        >
          <Space orientation="vertical" className="w-full text-center">
            <Text type="secondary">{t('tenant.genes.downloads')}</Text>
            <div className="flex items-center justify-center gap-2">
              <Download className="w-5 h-5 text-blue-500" />
              <Title level={3} className="!mb-0">
                {currentGene.install_count || 0}
              </Title>
            </div>
          </Space>
        </Card>

        <Card
          size="small"
          className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700"
        >
          <Space orientation="vertical" className="w-full text-center">
            <Text type="secondary">{t('tenant.genes.averageRating')}</Text>
            <div className="flex flex-col items-center justify-center">
              <Space>
                <Title level={3} className="!mb-0">
                  {currentGene.avg_rating?.toFixed(1) || '0.0'}
                </Title>
                <Rate disabled allowHalf value={currentGene.avg_rating || 0} className="text-sm" />
              </Space>
            </div>
          </Space>
        </Card>

        <Card
          size="small"
          className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700"
        >
          <Space orientation="vertical" className="w-full text-center">
            <Text type="secondary">{t('tenant.genes.tags')}</Text>
            <div className="flex flex-wrap items-center justify-center gap-1 mt-2">
              {currentGene.tags.length > 0 ? (
                currentGene.tags.map((tag) => (
                  <Tag key={tag} icon={<TagIcon className="w-3 h-3 mr-1 inline-block" />}>
                    {tag}
                  </Tag>
                ))
              ) : (
                <Text type="secondary">{t('tenant.genes.noTags')}</Text>
              )}
            </div>
          </Space>
        </Card>
      </div>

      <Card className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700">
        <Title level={4}>{t('tenant.genes.description')}</Title>
        <Paragraph className="whitespace-pre-wrap break-words">
          {currentGene.description || t('tenant.genes.noDescription')}
        </Paragraph>
      </Card>

      <Collapse
        items={[
          {
            key: 'manifest',
            label: <Text strong>{t('tenant.genes.manifest')}</Text>,
            children: (
              <pre className="p-4 bg-slate-50 dark:bg-slate-900 rounded-md overflow-x-auto text-sm border border-slate-200 dark:border-slate-700">
                {JSON.stringify(currentGene.manifest, null, 2)}
              </pre>
            ),
          },
        ]}
      />

      <Card className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700">
        <Title level={4} className="mb-6 flex items-center gap-2">
          <GitCommit className="w-5 h-5" />
          {t('tenant.genes.evolutionHistory')}
        </Title>

        {evolutionEvents.length > 0 ? (
          <EvolutionTimeline
            events={evolutionEvents}
            triggerLabel={t('tenant.genes.triggeredBy')}
          />
        ) : (
          <Text type="secondary">{t('tenant.genes.noEvolutionEvents')}</Text>
        )}
      </Card>

      <Card className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700">
        <div className="flex justify-between items-center mb-6">
          <Title level={4} className="!mb-0 flex items-center gap-2">
            <Star className="w-5 h-5" />
            {t('gene.reviews')}
          </Title>
          <Button
            type="primary"
            onClick={() => {
              setIsReviewModalVisible(true);
            }}
          >
            {t('gene.writeReview')}
          </Button>
        </div>

        {reviewsLoading ? (
          <SkeletonLoader type="list" count={2} />
        ) : reviews.length === 0 ? (
          <Empty description={t('gene.noReviews')} />
        ) : (
          <div role="list" className="divide-y divide-slate-200 dark:divide-slate-800">
            {reviews.map((review) => (
              <div
                key={review.id}
                role="listitem"
                className="flex items-start gap-3 py-4 first:pt-0 last:pb-0"
              >
                <Avatar icon={<User className="w-4 h-4 mt-1" />} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Text strong>{review.user_id}</Text>
                    <Rate disabled value={review.rating} className="text-sm" />
                    <Text type="secondary" className="ml-auto text-xs">
                      {formatDateOnly(review.created_at)}
                    </Text>
                  </div>
                  <Paragraph className="mt-2 mb-0 text-slate-700 dark:text-slate-300">
                    {review.content}
                  </Paragraph>
                </div>
                {currentUserId && review.user_id === currentUserId ? (
                  <Button
                    type="text"
                    danger
                    aria-label={t('gene.deleteReview')}
                    icon={<Trash2 className="w-4 h-4" />}
                    onClick={() => {
                      handleDeleteReview(review.id);
                    }}
                  />
                ) : null}
              </div>
            ))}
          </div>
        )}
        {reviewsTotal > 0 && (
          <div className="flex justify-end mt-4">
            <Pagination
              current={reviewPage}
              pageSize={reviewPageSize}
              total={reviewsTotal}
              onChange={(page) => {
                setReviewPage(page);
              }}
              showSizeChanger={false}
            />
          </div>
        )}
      </Card>

      <Modal
        title={t('gene.writeReview')}
        open={isReviewModalVisible}
        onOk={() => {
          void handleReviewSubmit();
        }}
        onCancel={() => {
          setIsReviewModalVisible(false);
          reviewForm.resetFields();
        }}
        confirmLoading={isReviewSubmitting}
      >
        <Form form={reviewForm} layout="vertical" className="mt-4" initialValues={{ rating: 5 }}>
          <Form.Item
            name="rating"
            label={t('gene.yourRating')}
            rules={[{ required: true, message: t('tenant.genes.ratingRequired') }]}
          >
            <Rate />
          </Form.Item>

          <Form.Item
            name="content"
            label={t('gene.reviewContent')}
            rules={[{ required: true, message: t('tenant.genes.commentPlaceholder') }]}
          >
            <Input.TextArea rows={4} placeholder={t('gene.reviewPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>

      <InstallEntityModal
        open={isInstallModalVisible}
        onClose={() => {
          setIsInstallModalVisible(false);
        }}
        entityKind="gene"
        installEntity={handleInstall}
      />

      <Modal
        title={t('tenant.genes.editGene', 'Edit Gene')}
        open={isEditModalVisible}
        onOk={() => {
          void handleEditSubmit();
        }}
        onCancel={() => {
          setIsEditModalVisible(false);
          editForm.resetFields();
        }}
        confirmLoading={isEditSubmitting}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical" className="mt-4">
          <GeneFormFields />
        </Form>
      </Modal>
    </div>
  );
};
