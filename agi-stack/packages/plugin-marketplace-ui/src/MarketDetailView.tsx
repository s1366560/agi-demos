import { useEffect, useRef, useState } from 'react';
import { menuPath } from '../../plugin-slots/src/richPage';
import { MarketDialog } from './MarketDialog';
import { marketName, localize, Mark, MarketStatus, PackageIcon, platforms } from './marketIcons';
import type { MarketText } from './pluginMarketText';
import {
  packageBase,
  packageScope,
  type Installation,
  type MarketDetail,
  type PluginMarketProps,
} from './pluginMarketTypes';

interface DetailProps extends PluginMarketProps {
  detail: MarketDetail;
  text: MarketText;
  version: string;
  onVersion(version: string): void;
  reload(): void;
  importLocal(): void;
}
type Operation = 'apply' | 'enable' | 'rollback' | 'disable' | 'uninstall';

function Values({ values }: { values: readonly string[] }) {
  return (
    <ul className="pm-tokens">
      {values.map((value) => (
        <li key={value}>{value}</li>
      ))}
    </ul>
  );
}

export function MarketDetailView(props: DetailProps) {
  const { detail: d, text: t, locale, tenantId, projectId } = props;
  const [review, setReview] = useState<{
    action: Operation;
    detail: MarketDetail;
  } | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const i = d.installation;
  const active = i?.running_version;
  const desired = i?.installed_version;
  const release = d.release;
  const running = release && release.digest === i?.actual_digest;
  const manages = props.canManage !== false && d.can_manage;
  const label = marketName(d, locale);
  const desc = localize(d.description, locale);
  const scope = packageScope(tenantId, projectId);
  const base = packageBase(projectId);
  const installedPages = (i?.pages ?? []).filter((page) => page.targets.includes(props.target));
  const previewPages = (release?.pages ?? []).filter((page) => page.targets.includes(props.target));
  const activeLinks = installedPages.flatMap((page) => {
    const path = page.routes.map((route) => menuPath(route, { tenantId, projectId })).find(Boolean);
    return path ? [{ id: page.id, path, title: page.title, home: page.home }] : [];
  });
  const home = activeLinks.find((link) => link.home) ?? activeLinks[0];
  const applicable = release && d.package_name && !d.source_error && !running;
  const actionLabel = !desired
    ? t.install
    : release?.version === desired && !active
      ? t.enable
      : release?.version === d.latest_version && d.update_available
        ? t.update + ' ' + release.version
        : t.switchVersion;
  const edit = (action: Operation) => setReview({ action, detail: d });
  const snapshot = review?.detail;
  const old = snapshot?.installation;
  const candidate = snapshot?.release;
  const oldPermissions = snapshot?.current_permissions ?? [];
  const newPermissions = candidate?.permissions ?? [];
  const added = newPermissions.filter((p) => !oldPermissions.includes(p));
  const removed = oldPermissions.filter((p) => !newPermissions.includes(p));
  const removedEntries = [
    ...new Set([...(old?.pages ?? []).map((p) => p.title), ...(old?.commands ?? [])]),
  ];

  async function submit() {
    if (!review || !snapshot || !manages) return;
    const expected_revision = snapshot.desired_revision;
    let response: Installation;
    if (review.action === 'apply' && candidate && snapshot.package_name) {
      try {
        response = await props.transport<Installation>(base + "/npm/apply", {
          method: "POST",
          body: {
            ...scope,
            package_name: snapshot.package_name,
            version: candidate.version,
            expected_digest: candidate.digest,
            expected_revision,
            approved_permissions: candidate.permissions,
          },
        });
      } catch (error) {
        // The server can commit a release before the desktop transport times out.
        // Reconcile the selected scope without submitting a second installation.
        const current = await props
          .transport<Installation>(
            base +
              "/" +
              encodeURIComponent(snapshot.plugin_id) +
              "?" +
              new URLSearchParams(scope),
            {},
          )
          .catch(() => null);
        if (
          !current ||
          current.plugin_id !== snapshot.plugin_id ||
          current.desired_revision <= expected_revision ||
          current.running_version !== candidate.version ||
          current.installed_version !== candidate.version ||
          current.actual_digest !== candidate.digest
        )
          throw error;
        response = current;
      }
    } else {
      response = await props.transport<Installation>(
        base + '/' + encodeURIComponent(d.plugin_id) + '/' + review.action,
        {
          method: 'POST',
          body: { ...scope, expected_revision },
        }
      );
    }
    if (review.action === 'apply' && response.actual_digest !== candidate?.digest) {
      throw new Error(response.failure || t.pending);
    }
    if (!mounted.current) return;
    setReview(null);
    props.onChanged?.();
    props.reload();
    if (review.action === 'apply') props.onActivated?.(response);
  }
  const activationTitle = old?.installed_version ? t.reviewUpdate : t.review;
  const confirmation =
    review?.action === 'uninstall'
      ? t.confirmUninstall
      : review?.action === 'disable'
        ? t.confirmDisable
        : review?.action === 'rollback'
          ? t.confirmRollback
          : review?.action === 'enable'
            ? t.enable
            : activationTitle;
  const confirmLabel =
    review?.action === 'apply'
      ? old?.installed_version
        ? t.approvedUpdate
        : t.permissionsApproved
      : review?.action === 'uninstall'
        ? t.uninstall
        : t.confirm;
  const selected = release?.version ?? props.version;
  const confirmedVersions = [...new Set([...d.versions, ...(selected ? [selected] : [])])];
  return (
    <>
      <div className="pm-detail-heading">
        <PackageIcon icon={d.icon} />
        <div className="pm-nameblock">
          <h2>{label}</h2>
          <span className="pm-mono">{d.package_name ?? d.plugin_id}</span>
        </div>
        <MarketStatus item={d} text={t} />
      </div>
      {desc && <p className="pm-description">{desc}</p>}
      <div className="pm-actions pm-detail-actions">
        {active && home && (
          <button
            type="button"
            className="pm-btn pm-primary"
            onClick={() => props.onOpen(home.path)}
          >
            {t.open}
            <Mark name="arrow" size={15} />
          </button>
        )}
        {applicable && manages && (
          <button
            type="button"
            className={'pm-btn' + (!active || !home ? ' pm-primary' : '')}
            onClick={() => edit('apply')}
          >
            {actionLabel}
          </button>
        )}
        {!applicable && desired && !active && manages && (
          <button type="button" className="pm-btn pm-primary" onClick={() => edit('enable')}>
            {t.enable}
          </button>
        )}
        {manages && (
          <details className="pm-menu">
            <summary className="pm-btn">
              <Mark name="more" size={16} />
              {t.more}
            </summary>
            <div className="pm-menu-list">
              {!!d.previous_version && (
                <button type="button" onClick={() => edit('rollback')}>
                  {t.rollback} {d.previous_version}
                </button>
              )}
              {active && (
                <button type="button" onClick={() => edit('disable')}>
                  {t.disable}
                </button>
              )}
              <button type="button" onClick={props.importLocal}>
                {t.local}
              </button>
              {desired && (
                <button type="button" className="pm-destructive" onClick={() => edit('uninstall')}>
                  {t.uninstall}
                </button>
              )}
            </div>
          </details>
        )}
      </div>
      {!manages && <p className="pm-muted">{t.readOnly}</p>}
      {i?.failure && (
        <div className="pm-warning" role="alert">
          <strong>{t.failed}</strong>
          <span>{i.failure}</span>
          <button type="button" className="pm-btn" onClick={props.reload}>
            {t.refresh}
          </button>
        </div>
      )}
      {d.release_error && (
        <p className="pm-error" role="alert">
          {d.release_error}
        </p>
      )}
      {d.source_error && (
        <div className="pm-warning" role="status">
          <strong>{t.offline}</strong>
          <span>{d.source_error}</span>
          <button type="button" className="pm-btn" onClick={props.reload}>
            {t.retry}
          </button>
        </div>
      )}
      <div className="pm-detail-grid">
        <div className="pm-detail-main">
          {active &&
            i?.actual_digest &&
            i.signed_slot_targets?.includes(props.target) &&
            props.declarativePage?.(i, d.can_execute === true)}
          <h3>{t.capabilities}</h3>
          {active && installedPages.length > 0 && (
            <>
              <h4>{release && !running ? `${t.pages} · ${t.active} ${active}` : t.pages}</h4>
              <ul className="pm-page-list">
                {installedPages.map((page) => {
                  const link = activeLinks.find((item) => item.id === page.id);
                  return (
                    <li key={page.id}>
                      {link ? (
                        <button type="button" onClick={() => props.onOpen(link.path)}>
                          {page.title}
                          <Mark name="arrow" size={14} />
                        </button>
                      ) : page.title}
                    </li>
                  );
                })}
              </ul>
            </>
          )}
          {release && !running && previewPages.length > 0 && (
            <>
              <h4>{t.pages} · {t.release} {release.version}</h4>
              <ul className="pm-page-list">
                {previewPages.map((page) => <li key={page.id}>{page.title}</li>)}
              </ul>
            </>
          )}
          <h4>{t.commands}</h4>
          {(release?.commands ?? i?.commands)?.length ? (
            <Values values={release?.commands ?? i?.commands ?? []} />
          ) : (
            <span className="pm-muted">{t.none}</span>
          )}
          <h3 className="pm-divided">
            <Mark name="lock" />
            {t.permissions}
          </h3>
          {(release?.permissions ?? d.current_permissions).length ? (
            <Values values={release?.permissions ?? d.current_permissions} />
          ) : (
            <p className="pm-muted">{t.noPermissions}</p>
          )}
          {props.target === 'desktop-renderer' &&
            i?.actual_digest &&
            i.targets?.includes('desktop-sidecar') &&
            props.deviceSettings?.(
              d.plugin_id,
              i.actual_digest,
              d.package_name && active
                ? { packageName: d.package_name, version: active }
                : undefined
            )}
        </div>
        <aside className="pm-spec">
          <h3>{t.versions}</h3>
          {confirmedVersions.length > 0 && (
            <label>
              {t.selectVersion}
              <select
                aria-label={t.selectVersion}
                value={selected || confirmedVersions[0]}
                onChange={(e) => props.onVersion(e.target.value)}
              >
                {confirmedVersions.map((v) => (
                  <option value={v} key={v}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
          )}
          <dl>
            <dt>{t.active}</dt>
            <dd>{active ?? t.noRunning}</dd>
            <dt>{t.chosen}</dt>
            <dd>{desired ?? t.none}</dd>
            <dt>{t.targets}</dt>
            <dd>{platforms(release?.targets ?? d.targets, t).join(' · ') || t.unknown}</dd>
            <dt>{t.source}</dt>
            <dd>{d.source || t.localOnly}</dd>
            {(release || i?.actual_digest) && (
              <>
                <dt>{t.digest}</dt>
                <dd className="pm-digest">{release?.digest ?? i?.actual_digest}</dd>
              </>
            )}
          </dl>
        </aside>
      </div>
      {review && (
        <MarketDialog
          text={t}
          title={confirmation}
          confirmLabel={confirmLabel}
          danger={review.action === 'uninstall'}
          onClose={() => {
            setReview(null);
            props.reload();
          }}
          onConfirm={submit}
        >
          <strong>{label}</strong>
          <p>{t.scopeLabel} · {projectId ?? tenantId}</p>
          {review.action === 'apply' && candidate && (
            <>
              <p className="pm-release-line">
                {old?.running_version && (
                  <>
                    {old.running_version}
                    <Mark name="arrow" size={16} />
                  </>
                )}
                {candidate.version}
              </p>
              {old?.installed_version ? (
                <>
                  {added.length > 0 && (
                    <>
                      <h4>{t.added}</h4>
                      <Values values={added} />
                    </>
                  )}
                  {removed.length > 0 && (
                    <>
                      <h4>{t.removed}</h4>
                      <Values values={removed} />
                    </>
                  )}
                  {!added.length && !removed.length && <p>{t.unchanged}</p>}
                </>
              ) : (
                <>
                  <h4>{t.permissions}</h4>
                  {candidate.permissions.length ? (
                    <Values values={candidate.permissions} />
                  ) : (
                    <p>{t.noPermissions}</p>
                  )}
                </>
              )}
              <p className="pm-digest">{candidate.digest}</p>
            </>
          )}
          {review.action === 'uninstall' && (
            <>
              <p>{removedEntries.length ? t.retention : t.retentionEmpty}</p>
              <Values values={removedEntries} />
            </>
          )}
          {review.action === 'disable' && <p>{t.disabledNote}</p>}
          {review.action === 'rollback' && (
            <p className="pm-release-line">
              {active}
              <Mark name="arrow" size={16} />
              {snapshot?.previous_version}
            </p>
          )}
          {review.action === 'enable' && <p>{desired}</p>}
        </MarketDialog>
      )}
    </>
  );
}
