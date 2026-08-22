import { Fragment, lazy, Suspense } from 'react';

import { Navigate, Route, Routes } from 'react-router-dom';

import { ErrorBoundary } from './components/common/ErrorBoundary';
import './i18n/config';
import { Login } from './pages/Login';
import { WebPluginGenerationHostV2 } from './plugins/WebPluginGenerationHostV2';
import { LoginRedirect, RedirectToLogin } from './routes/v2/webCoreRouteRedirectsV2';
import { WebRouteAuthorityProviderV2 } from './routes/v2/WebRouteAuthorityV2';
import { WebRoutePageLoaderV2 as PageLoader } from './routes/v2/WebRoutePageLoaderV2';
import { useAuthStore } from './stores/auth';
import { ThemeProvider } from './theme';
import './App.css';

// ============================================================================
// CODE SPLITTING - Lazy load route components for better performance
// ============================================================================
// Components are loaded on-demand, reducing initial bundle size
// ============================================================================

// Auth pages
const ForceChangePassword = lazy(() =>
  import('./pages/ForceChangePassword').then((m) => ({ default: m.ForceChangePassword }))
);
const OAuthCallback = lazy(() =>
  import('./pages/OAuthCallback').then((m) => ({ default: m.OAuthCallback }))
);
const InviteAccept = lazy(() =>
  import('./pages/InviteAccept').then((m) => ({ default: m.InviteAccept }))
);
const DeviceApprove = lazy(() =>
  import('./pages/DeviceApprove').then((m) => ({ default: m.DeviceApprove }))
);
const NotFound = lazy(() => import('./pages/NotFound').then((m) => ({ default: m.NotFound })));

function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const mustChangePassword = isAuthenticated && user?.must_change_password === true;

  return (
    <ErrorBoundary>
      <ThemeProvider>
        <Suspense fallback={<PageLoader />}>
          <WebPluginGenerationHostV2 enabled={isAuthenticated}>
            <WebRouteAuthorityProviderV2 enabled={isAuthenticated}>
              {({ routeArtifacts, status }) => (
                <Routes>
                  <Route path="/login" element={!isAuthenticated ? <Login /> : <LoginRedirect />} />
                  <Route
                    path="/login/callback/:provider"
                    element={
                      <Suspense fallback={<PageLoader />}>
                        <OAuthCallback />
                      </Suspense>
                    }
                  />
                  <Route
                    path="/invite/:token"
                    element={
                      <Suspense fallback={<PageLoader />}>
                        <InviteAccept />
                      </Suspense>
                    }
                  />
                  <Route
                    path="/device"
                    element={
                      isAuthenticated ? (
                        <Suspense fallback={<PageLoader />}>
                          <DeviceApprove />
                        </Suspense>
                      ) : (
                        <RedirectToLogin />
                      )
                    }
                  />

                  {/* Force Change Password */}
                  <Route
                    path="/force-change-password"
                    element={
                      isAuthenticated ? (
                        <Suspense fallback={<PageLoader />}>
                          <ForceChangePassword />
                        </Suspense>
                      ) : (
                        <Navigate to="/login" replace />
                      )
                    }
                  />

                  {/* Protected Routes */}
                  {/* Redirect root to tenant overview if authenticated */}
                  <Route
                    path="/"
                    element={
                      mustChangePassword ? (
                        <Navigate to="/force-change-password" replace />
                      ) : isAuthenticated ? (
                        <Navigate to="/tenant" replace />
                      ) : (
                        <Navigate to="/login" replace />
                      )
                    }
                  />

                  {status === 'ready'
                    ? routeArtifacts.map((artifact) => (
                        <Fragment key={artifact.id}>{artifact.createRouteElements()}</Fragment>
                      ))
                    : null}

                  {/* Fallback */}
                  <Route
                    path="*"
                    element={
                      isAuthenticated && status === 'loading' ? (
                        <PageLoader />
                      ) : (
                        <Suspense fallback={<PageLoader />}>
                          <NotFound />
                        </Suspense>
                      )
                    }
                  />
                </Routes>
              )}
            </WebRouteAuthorityProviderV2>
          </WebPluginGenerationHostV2>
        </Suspense>
      </ThemeProvider>
    </ErrorBoundary>
  );
}

export default App;
