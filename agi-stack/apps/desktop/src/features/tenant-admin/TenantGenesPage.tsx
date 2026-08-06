import { useState, type FormEvent } from 'react';

import { useI18n } from '../../i18n';
import type { TenantGenesController } from './tenantGenesController';
import type { TenantGenesViewModel } from './tenantGenesPresentationModel';
import { TenantAdminDegradedNotice, TenantAdminRouteState } from './TenantAdminRouteState';

export function TenantGenesPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantGenesViewModel;
  controller: TenantGenesController | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [geneName, setGeneName] = useState('');
  const [geneSlug, setGeneSlug] = useState('');
  const [selectedGeneId, setSelectedGeneId] = useState('');
  const [instanceId, setInstanceId] = useState('');
  const [rating, setRating] = useState('5');
  const [comment, setComment] = useState('');
  const [reviewId, setReviewId] = useState('');
  const activeGeneId = selectedGeneId || model.genes[0]?.id || '';
  const busy = Boolean(model.busyAction);
  const allows = (action: string) => model.allowedActions.includes(action);

  if (!['ready', 'degraded', 'empty', 'stale'].includes(model.state)) {
    return (
      <TenantAdminRouteState
        state={model.state}
        reasonCode={model.reasonCode}
        retryVisible={model.retryVisible}
        onRetry={onRetry}
      />
    );
  }

  const submitCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!controller) return;
    const createGene = controller.createGene;
    void createGene({ name: geneName, slug: geneSlug })
      .then(() => {
        setGeneName('');
        setGeneSlug('');
      })
      .catch(() => undefined);
  };
  const updateSelected = () => {
    if (!controller || !activeGeneId) return;
    const updateGene = controller.updateGene;
    void updateGene(activeGeneId, { name: geneName, slug: geneSlug })
      .catch(() => undefined);
  };
  const deleteSelected = () => {
    if (!controller || !activeGeneId) return;
    void controller.deleteGene(activeGeneId).catch(() => undefined);
  };
  const publishSelected = () => {
    if (!controller || !activeGeneId) return;
    void controller.publishGene(activeGeneId).catch(() => undefined);
  };
  const unpublishSelected = () => {
    if (!controller || !activeGeneId) return;
    void controller.unpublishGene(activeGeneId).catch(() => undefined);
  };
  const installSelected = () => {
    if (!controller || !activeGeneId) return;
    void controller.installGene(instanceId, activeGeneId).catch(() => undefined);
  };
  const rateSelected = () => {
    if (!controller || !activeGeneId) return;
    void controller.rateGene(activeGeneId, Number(rating), comment).catch(() => undefined);
  };
  const createSelectedReview = () => {
    if (!controller || !activeGeneId) return;
    const createReview = controller.createReview;
    void createReview(activeGeneId, Number(rating), comment)
      .catch(() => undefined);
  };
  const deleteSelectedReview = () => {
    if (!controller || !activeGeneId) return;
    void controller.deleteReview(activeGeneId, reviewId).catch(() => undefined);
  };

  return (
    <section data-tenant-management-route="genes" data-state={model.state}>
      <header>
        <h1>{t('tenantAdmin.genes.title')}</h1>
        <p>{t('tenantAdmin.genes.subtitle')}</p>
        <code>{model.scope.tenantId}</code>
      </header>
      <TenantAdminDegradedNotice reasonCode={model.reasonCode} />
      <button type="button" onClick={onRetry} disabled={busy}>
        {t('common.refresh')}
      </button>
      <p>{t('tenantAdmin.total', { count: model.total })}</p>

      {controller && allows('create') ? (
        <form onSubmit={submitCreate}>
          <label>
            {t('tenantAdmin.genes.name')}
            <input
              value={geneName}
              onChange={(event) => setGeneName(event.target.value)}
              required
            />
          </label>
          <label>
            {t('tenantAdmin.genes.slug')}
            <input
              value={geneSlug}
              onChange={(event) => setGeneSlug(event.target.value)}
              required
            />
          </label>
          <button type="submit" disabled={busy}>
            {t('tenantAdmin.genes.create')}
          </button>
        </form>
      ) : null}

      <label>
        {t('tenantAdmin.genes.selected')}
        <select value={activeGeneId} onChange={(event) => setSelectedGeneId(event.target.value)}>
          <option value="">{t('tenantAdmin.genes.select')}</option>
          {model.genes.map((gene) => (
            <option key={gene.id} value={gene.id}>
              {gene.name}
            </option>
          ))}
        </select>
      </label>

      <div>
        {controller && allows('update') ? (
          <button type="button" disabled={busy || !activeGeneId} onClick={updateSelected}>
            {t('tenantAdmin.genes.update')}
          </button>
        ) : null}
        {controller && allows('delete') ? (
          <button type="button" disabled={busy || !activeGeneId} onClick={deleteSelected}>
            {t('common.delete')}
          </button>
        ) : null}
        {controller && allows('publish') ? (
          <button type="button" disabled={busy || !activeGeneId} onClick={publishSelected}>
            {t('tenantAdmin.genes.publish')}
          </button>
        ) : null}
        {controller && allows('unpublish') ? (
          <button type="button" disabled={busy || !activeGeneId} onClick={unpublishSelected}>
            {t('tenantAdmin.genes.unpublish')}
          </button>
        ) : null}
      </div>

      <fieldset disabled={busy || !activeGeneId}>
        <legend>{t('tenantAdmin.genes.communityActions')}</legend>
        <label>
          {t('tenantAdmin.genes.instance')}
          <input value={instanceId} onChange={(event) => setInstanceId(event.target.value)} />
        </label>
        {controller && allows('install') ? (
          <button type="button" onClick={installSelected}>
            {t('tenantAdmin.genes.install')}
          </button>
        ) : null}
        <label>
          {t('tenantAdmin.genes.rating')}
          <input
            type="number"
            min="1"
            max="5"
            value={rating}
            onChange={(event) => setRating(event.target.value)}
          />
        </label>
        <label>
          {t('tenantAdmin.genes.comment')}
          <input value={comment} onChange={(event) => setComment(event.target.value)} />
        </label>
        {controller && allows('rate') ? (
          <button type="button" onClick={rateSelected}>
            {t('tenantAdmin.genes.rate')}
          </button>
        ) : null}
        {controller && allows('create-review') ? (
          <button type="button" onClick={createSelectedReview}>
            {t('tenantAdmin.genes.createReview')}
          </button>
        ) : null}
        <label>
          {t('tenantAdmin.genes.reviewId')}
          <input value={reviewId} onChange={(event) => setReviewId(event.target.value)} />
        </label>
        {controller && allows('delete-own-review') ? (
          <button type="button" onClick={deleteSelectedReview}>
            {t('tenantAdmin.genes.deleteReview')}
          </button>
        ) : null}
      </fieldset>

      <ul>
        {model.genes.map((gene) => (
          <li key={gene.id}>
            <strong>{gene.name}</strong>
            <span>{gene.version}</span>
            <span>{gene.description}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
