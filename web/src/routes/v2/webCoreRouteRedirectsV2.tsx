import { Navigate, useLocation, useSearchParams } from 'react-router-dom';

// Redirect after successful login: honour location.state.from (react-router
// convention) or the ?redirect= query param when it is a same-origin path.
// Falls back to '/'. Exists so that deep links such as /device?user_code=X
// can be preserved through the login round-trip.
export const LoginRedirect = () => {
  const [params] = useSearchParams();
  const location = useLocation();
  const stateFrom = (location.state as { from?: unknown } | null)?.from;
  let statePath: string | null = null;
  if (typeof stateFrom === 'string') {
    statePath = stateFrom;
  } else if (stateFrom && typeof stateFrom === 'object') {
    const { pathname, search } = stateFrom as { pathname?: unknown; search?: unknown };
    if (typeof pathname === 'string') {
      statePath = pathname + (typeof search === 'string' ? search : '');
    }
  }
  const raw = statePath ?? params.get('redirect');
  const safe = raw && raw.startsWith('/') && !raw.startsWith('//') ? raw : '/';
  return <Navigate to={safe} replace />;
};

// Redirect unauthenticated users to /login while preserving the current
// location (path + search) as ?redirect=, so that after sign-in they are
// returned to where they originally wanted to go. Paired with LoginRedirect.
export const RedirectToLogin = () => {
  const location = useLocation();
  const target = `${location.pathname}${location.search}`;
  const safe = target.startsWith('/') && !target.startsWith('//') ? target : '/';
  const loginHref =
    safe === '/' || safe === '/login' ? '/login' : `/login?redirect=${encodeURIComponent(safe)}`;
  return <Navigate to={loginHref} replace />;
};
