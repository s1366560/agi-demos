import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router-dom';

export function compatibilityUrl(
  location: Pick<Location, 'pathname' | 'search' | 'hash'>,
  host: URL,
  configured?: string
) {
  try {
    const origin =
      configured ||
      (['localhost', '127.0.0.1', '[::1]'].includes(host.hostname)
        ? host.protocol + '//' + host.hostname + ':3001'
        : '');
    if (!origin) return null;
    const target = new URL(origin);
    if (
      !['https:', 'http:'].includes(target.protocol) ||
      target.username ||
      target.password ||
      target.origin === host.origin ||
      target.pathname !== '/' ||
      target.search ||
      target.hash
    )
      return null;
    // Only transplant location fields, never resolve a user-supplied authority or copy a session.
    target.pathname = location.pathname;
    target.search = location.search;
    target.hash = location.hash;
    return target.href;
  } catch {
    return null;
  }
}

export function CompatibilityPage({ market }: { market?: string }) {
  const location = useLocation();
  const { t } = useTranslation();
  const href = compatibilityUrl(
    location,
    new URL(window.location.href),
    import.meta.env.VITE_COMPAT_WORKBENCH_ORIGIN
  );
  return (
    <section className="space-y-4 p-6">
      <h1 className="text-xl font-semibold">{t('fullHost.unavailable')}</h1>
      {market && (
        <Link
          className="text-primary"
          to={
            market +
            (market.includes('?') ? '&' : '?') +
            new URLSearchParams({ returnTo: location.pathname + location.search + location.hash })
          }
        >
          {t('tenant.pluginHub.backToMarket')}
        </Link>
      )}
      {href && (
        <p>
          <a className="text-primary" href={href}>
            {t('fullHost.compatibility')}
          </a>
        </p>
      )}
    </section>
  );
}
