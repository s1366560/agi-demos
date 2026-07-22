import { useTranslation } from 'react-i18next';

import { Form, Input, Select } from 'antd';

import { visibilityOptions } from '../geneVisibility';

/**
 * Shared gene form fields (name/slug/version/category/descriptions/visibility/tags)
 * used by the GeneMarket publish modal and the GeneDetail edit modal.
 * Render inside an antd <Form>.
 */
export const GeneFormFields: React.FC = () => {
  const { t } = useTranslation();
  return (
    <>
      <Form.Item
        name="name"
        label={t('tenant.genes.publish.name', 'Name')}
        rules={[{ required: true, message: t('tenant.genes.publish.nameRequired') }]}
      >
        <Input placeholder={t('tenant.genes.publish.namePlaceholder')} />
      </Form.Item>
      <Form.Item
        name="slug"
        label={t('tenant.genes.publish.slug', 'Slug')}
        rules={[{ required: true, message: t('tenant.genes.publish.slugRequired') }]}
      >
        <Input placeholder={t('tenant.genes.publish.slugPlaceholder')} />
      </Form.Item>
      <Form.Item
        name="version"
        label={t('tenant.genes.publish.version', 'Version')}
        rules={[
          { required: true, message: t('tenant.genes.versionRequired', 'Version is required') },
        ]}
      >
        <Input placeholder="1.0.0" />
      </Form.Item>
      <Form.Item name="category" label={t('tenant.genes.publish.category', 'Category')}>
        <Input placeholder={t('tenant.genes.publish.categoryPlaceholder')} />
      </Form.Item>
      <Form.Item
        name="short_description"
        label={t('tenant.genes.publish.shortDescription', 'Short description')}
      >
        <Input placeholder={t('tenant.genes.publish.shortDescriptionPlaceholder')} />
      </Form.Item>
      <Form.Item name="description" label={t('tenant.genes.description', 'Description')}>
        <Input.TextArea rows={4} placeholder={t('tenant.genes.publish.descriptionPlaceholder')} />
      </Form.Item>
      <Form.Item name="visibility" label={t('tenant.genes.publish.visibility', 'Visibility')}>
        <Select options={[...visibilityOptions(t)]} />
      </Form.Item>
      <Form.Item name="tags" label={t('tenant.genes.publish.tags', 'Tags')}>
        <Input placeholder={t('tenant.genes.publish.tagsPlaceholder')} />
      </Form.Item>
    </>
  );
};
