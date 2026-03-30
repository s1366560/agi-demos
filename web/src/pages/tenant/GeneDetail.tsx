import { useEffect, useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';

import {
  Button,
  Badge,
  Card,
  Tag,
  Modal,
  Form,
  Input,
  Rate,
  Timeline,
  Typography,
  Space,
  message,
  Spin,
  List,
  Avatar,
  Pagination,
  Collapse,
} from 'antd';
import { Download, Star, Tag as TagIcon, ArrowLeft, GitCommit, User, Trash2 } from 'lucide-react';

import {
  useCurrentGene,
  useGeneReviews,
  useGeneReviewsTotal,
  useGeneReviewsLoading,
  useEvolutionEvents,
  useGeneMarketLoading,
  useGeneMarketActions,
} from '../../stores/geneMarket';

const { Title, Text, Paragraph } = Typography;

interface InstallFormValues {
  instance_id: string;
  config_override?: string;
}

interface RateFormValues {
  score: number;
  comment?: string;
}

interface ReviewFormValues {
  rating: number;
  content: string;
}

export const GeneDetail: FC = () => {
  const { geneId } = useParams<{ geneId: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const currentGene = useCurrentGene();
  const evolutionEvents = useEvolutionEvents();
  const isLoading = useGeneMarketLoading();
  const reviews = useGeneReviews();
  const reviewsTotal = useGeneReviewsTotal();
  const reviewsLoading = useGeneReviewsLoading();
  const {
    getGene,
    installGene,
    rateGene,
    listEvolutionEvents,
    clearError,
    reset,
    fetchGeneReviews,
    createGeneReview,
    deleteGeneReview,
  } = useGeneMarketActions();

  const [isInstallModalVisible, setIsInstallModalVisible] = useState(false);
  const [isRateModalVisible, setIsRateModalVisible] = useState(false);
  const [installForm] = Form.useForm<InstallFormValues>();
  const [rateForm] = Form.useForm<RateFormValues>();
  const [isReviewModalVisible, setIsReviewModalVisible] = useState(false);
  const [reviewForm] = Form.useForm<ReviewFormValues>();
  const [reviewPage, setReviewPage] = useState(1);
  const reviewPageSize = 5;

  useEffect(() => {
    if (geneId) {
      getGene(geneId).catch(() => message.error(t('tenant.genes.fetchError')));
      listEvolutionEvents(geneId).catch(() => {});
      fetchGeneReviews(geneId, reviewPage, reviewPageSize).catch(() => {});
    }
    return () => {
      clearError();
      reset();
    };
  }, [geneId, getGene, listEvolutionEvents, fetchGeneReviews, clearError, reset, t, reviewPage]);

  const handleInstallSubmit = async () => {
    try {
      const values = await installForm.validateFields();
      let configOverride: Record<string, unknown> = {};
      if (values.config_override) {
        configOverride = JSON.parse(values.config_override) as Record<string, unknown>;
      }

      await installGene(values.instance_id, {
        gene_id: geneId ?? '',
        config: configOverride,
      });
      message.success(t('tenant.genes.installSuccess'));
      setIsInstallModalVisible(false);
      installForm.resetFields();
    } catch (err) {
      if (err instanceof Error && err.message.includes('Unexpected token')) {
        message.error(t('tenant.genes.invalidJson'));
      } else if (err instanceof Error) {
        message.error(err.message);
      }
    }
  };

  const handleRateSubmit = async () => {
    try {
      const values = await rateForm.validateFields();
      if (geneId) {
        await rateGene(geneId, {
          score: values.score,
          comment: values.comment ?? null,
        });
        message.success(t('tenant.genes.rateSuccess'));
        setIsRateModalVisible(false);
        rateForm.resetFields();
        void getGene(geneId);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleReviewSubmit = async () => {
    try {
      const values = await reviewForm.validateFields();
      if (geneId) {
        await createGeneReview(geneId, {
          rating: values.rating,
          content: values.content,
        });
        message.success(t('gene.reviewSubmitSuccess'));
        setIsReviewModalVisible(false);
        reviewForm.resetFields();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteReview = (reviewId: string) => {
    Modal.confirm({
      title: t('gene.deleteReview'),
      content: t('gene.deleteReviewConfirm'),
      okText: t('common.yes'),
      cancelText: t('common.no'),
      onOk: async () => {
        if (geneId) {
          try {
            await deleteGeneReview(geneId, reviewId);
            message.success(t('gene.reviewDeleteSuccess'));
          } catch (err) {
            console.error(err);
          }
        }
      },
    });
  };

  const getEventColor = (type: string) => {
    switch (type) {
      case 'installed':
        return 'green';
      case 'uninstalled':
        return 'red';
      case 'upgraded':
        return 'blue';
      case 'configured':
        return 'orange';
      case 'rollback':
        return 'purple';
      default:
        return 'gray';
    }
  };

  if (isLoading && !currentGene) {
    return (
      <div className="flex justify-center items-center h-64">
        <Spin size="large" />
      </div>
    );
  }

  if (!currentGene) {
    return (
      <div className="text-center mt-12">
        <Title level={4}>{t('tenant.genes.notFound')}</Title>
        <Button onClick={() => navigate(-1)} icon={<ArrowLeft className="w-4 h-4" />}>
          {t('tenant.genes.back')}
        </Button>
      </div>
    );
  }

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      <div className="flex justify-between items-start">
        <Space direction="vertical" size="small">
          <Button
            type="text"
            icon={<ArrowLeft className="w-4 h-4" />}
            onClick={() => navigate(-1)}
            className="pl-0"
          >
            {t('tenant.genes.back')}
          </Button>
          <Space align="center" size="middle" className="mt-2">
            <Title level={2} className="!mb-0">
              {currentGene.name}
            </Title>
            <Badge count={`v${currentGene.version}`} style={{ backgroundColor: '#108ee9' }} />
            {currentGene.category && <Tag color="purple">{currentGene.category}</Tag>}
            <Tag color={currentGene.visibility === 'public' ? 'green' : 'default'}>
              {currentGene.visibility}
            </Tag>
          </Space>
        </Space>

        <Space>
          <Button
            onClick={() => {
              setIsRateModalVisible(true);
            }}
            icon={<Star className="w-4 h-4" />}
          >
            {t('tenant.genes.rateAction')}
          </Button>
          <Button
            type="primary"
            onClick={() => {
              setIsInstallModalVisible(true);
            }}
            icon={<Download className="w-4 h-4" />}
          >
            {t('tenant.genes.installAction')}
          </Button>
        </Space>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
        <Card
          size="small"
          className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700"
        >
          <Space direction="vertical" className="w-full text-center">
            <Text type="secondary">{t('tenant.genes.downloads')}</Text>
            <div className="flex items-center justify-center gap-2">
              <Download className="w-5 h-5 text-blue-500" />
              <Title level={3} className="!mb-0">
                {currentGene.download_count || 0}
              </Title>
            </div>
          </Space>
        </Card>

        <Card
          size="small"
          className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700"
        >
          <Space direction="vertical" className="w-full text-center">
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
          <Space direction="vertical" className="w-full text-center">
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
        <Paragraph className="whitespace-pre-wrap">
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
          <Timeline
            items={evolutionEvents.map((event) => ({
              color: getEventColor(event.event_type),
              children: (
                <div className="flex flex-col gap-1 mb-4">
                  <div className="flex items-center gap-2">
                    <Tag color={getEventColor(event.event_type)}>{event.event_type}</Tag>
                    <Text type="secondary" className="text-xs">
                      {new Date(event.created_at).toLocaleString()}
                    </Text>
                  </div>
                  <Text strong>{event.event_type}</Text>
                  {(event.from_version || event.to_version) && (
                    <div className="text-xs font-mono bg-slate-50 dark:bg-slate-900 p-2 rounded mt-2 border border-slate-200 dark:border-slate-800">
                      <div className="text-slate-500">
                        {event.from_version || 'none'}
                        <span className="mx-2">→</span>
                        {event.to_version || 'none'}
                      </div>
                    </div>
                  )}
                  {event.trigger && (
                    <Text type="secondary" className="text-xs mt-1">
                      {t('tenant.genes.triggeredBy')}: {event.trigger}
                    </Text>
                  )}
                </div>
              ),
            }))}
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

        <List
          loading={reviewsLoading}
          dataSource={reviews}
          locale={{ emptyText: t('gene.noReviews') }}
          renderItem={(review) => (
            <List.Item
              actions={[
                <Button
                  type="text"
                  danger
                  icon={<Trash2 className="w-4 h-4" />}
                  onClick={() => {
                    handleDeleteReview(review.id);
                  }}
                />,
              ]}
            >
              <List.Item.Meta
                avatar={<Avatar icon={<User className="w-4 h-4 mt-1" />} />}
                title={
                  <div className="flex items-center gap-2">
                    <Text strong>{review.user_id}</Text>
                    <Rate disabled value={review.rating} className="text-sm" />
                    <Text type="secondary" className="text-xs ml-auto">
                      {new Date(review.created_at).toLocaleDateString()}
                    </Text>
                  </div>
                }
                description={
                  <Paragraph className="mt-2 mb-0 text-slate-700 dark:text-slate-300">
                    {review.content}
                  </Paragraph>
                }
              />
            </List.Item>
          )}
        />
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
        onOk={handleReviewSubmit}
        onCancel={() => {
          setIsReviewModalVisible(false);
          reviewForm.resetFields();
        }}
        confirmLoading={isLoading}
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

      <Modal
        title={t('tenant.genes.installGene')}
        open={isInstallModalVisible}
        onOk={handleInstallSubmit}
        onCancel={() => {
          setIsInstallModalVisible(false);
          installForm.resetFields();
        }}
        confirmLoading={isLoading}
      >
        <Form form={installForm} layout="vertical" className="mt-4">
          <Form.Item
            name="instance_id"
            label={t('tenant.genes.instanceId')}
            rules={[{ required: true, message: t('tenant.genes.instanceIdRequired') }]}
          >
            <Input placeholder={t('tenant.genes.instanceIdPlaceholder')} />
          </Form.Item>

          <Form.Item
            name="config_override"
            label={t('tenant.genes.configOverride')}
            tooltip={t('tenant.genes.configOverrideTooltip')}
          >
            <Input.TextArea rows={4} placeholder='{"key": "value"}' className="font-mono text-sm" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t('tenant.genes.rateGene')}
        open={isRateModalVisible}
        onOk={handleRateSubmit}
        onCancel={() => {
          setIsRateModalVisible(false);
          rateForm.resetFields();
        }}
        confirmLoading={isLoading}
      >
        <Form form={rateForm} layout="vertical" className="mt-4" initialValues={{ score: 5 }}>
          <Form.Item
            name="score"
            label={t('tenant.genes.rating')}
            rules={[{ required: true, message: t('tenant.genes.ratingRequired') }]}
          >
            <Rate allowHalf />
          </Form.Item>

          <Form.Item name="comment" label={t('tenant.genes.comment')}>
            <Input.TextArea rows={4} placeholder={t('tenant.genes.commentPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};
