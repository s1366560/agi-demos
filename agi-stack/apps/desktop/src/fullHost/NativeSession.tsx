import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  desktopCloudSessionProjectionClient,
  type CloudSessionProjection,
} from '../api/cloudSessionProjectionClient';
import {
  desktopNativeCloudAuthClient,
  type NativeDeviceAuthorizationOpened,
} from '../api/nativeCloudAuthClient';
import { desktopNativeOAuthClient, type NativeOAuthProvider } from '../api/nativeOAuthClient';
import { ForcePasswordChangeScreen } from '../features/auth/ForcePasswordChangeScreen';
import { LoginScreen } from '../features/auth/LoginScreen';
import { initialDesktopRuntimeConfig } from '../features/auth/loginRuntimeModel';
import { DEFAULT_CONFIG } from '../types';
import { FullWorkbench } from './FullWorkbench';

type Phase = 'loading' | 'signed_out' | 'signing_in' | 'password_change_required' | 'signed_in';

export function NativeSession() {
  const auth = useMemo(desktopNativeCloudAuthClient, []);
  const projection = useMemo(desktopCloudSessionProjectionClient, []);
  const oauth = useMemo(desktopNativeOAuthClient, []);
  const [session, setSession] = useState<CloudSessionProjection | null>(null);
  const [phase, setPhase] = useState<Phase>('loading');
  const [origin, setOrigin] = useState(() => initialDesktopRuntimeConfig().apiBaseUrl);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<NativeDeviceAuthorizationOpened | null>(null);
  const [providers, setProviders] = useState<readonly NativeOAuthProvider[]>([]);
  const [provider, setProvider] = useState<string | null>(null);
  const generation = useRef(0);

  const fail = useCallback((cause: unknown) => {
    setError(String(cause));
    setPhase('signed_out');
  }, []);

  const restore = useCallback(
    async (revision = generation.current) => {
      if (!projection) throw new Error('native_cloud_session_unavailable');
      let next: CloudSessionProjection | null;
      let needsScope = false;
      try {
        next = await projection.load();
      } catch (cause) {
        if (!String(cause).includes('cloud_project_selection_required')) throw cause;
        next = null;
        needsScope = true;
      }
      if (revision !== generation.current) return;
      setSession(next);
      setPending(null);
      setProvider(null);
      setPassword('');
      setError(null);
      setPhase(next || needsScope ? 'signed_in' : 'signed_out');
    },
    [projection],
  );

  useEffect(() => {
    const revision = ++generation.current;
    async function initialize() {
      if (!auth) throw new Error('native_authentication_unavailable');
      const status = await auth.getStatus();
      if (revision !== generation.current) return;
      if (status.status === 'authenticated') await restore(revision);
      else setPhase(status.status === 'password_change_required' ? status.status : 'signed_out');
    }
    void initialize().catch((cause) => {
      if (revision === generation.current) fail(cause);
    });
    const stop = window.__MEMSTACK_DESKTOP__?.events?.onCloudSessionInvalidated?.(() => {
      generation.current++;
      setSession(null);
      setPassword('');
      setPending(null);
      setProvider(null);
      fail('cloud_session_expired');
    });
    return () => {
      generation.current++;
      stop?.();
    };
  }, [auth, fail, restore]);

  useEffect(() => {
    if (!oauth || phase !== 'signed_out') return;
    let current = true;
    setProviders([]);
    void oauth
      .listProviders({ apiBaseUrl: origin })
      .then((items) => {
        if (current) setProviders(items);
      })
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [origin, oauth, phase]);

  useEffect(
    () =>
      oauth?.subscribe((event) => {
        if (event.status === 'authenticated') {
          void restore()
            .then(() => {
              window.location.hash = event.resumeRoute;
            })
            .catch(fail);
        } else {
          setProvider(null);
          fail(event.reasonCode);
        }
      }),
    [oauth, restore, fail],
  );

  useEffect(() => {
    if (!auth || !pending) return;
    let current = true;
    let timer: number;
    const poll = async () => {
      try {
        const result = await auth.pollDeviceAuthorization(pending.attemptId);
        if (!current) return;
        if (result.status === 'authenticated') await restore();
        else if (result.status === 'expired') {
          setPending(null);
          fail('device_authorization_expired');
        } else timer = window.setTimeout(poll, 1000 * result.interval);
      } catch (cause) {
        if (current) {
          setPending(null);
          fail(cause);
        }
      }
    };
    timer = window.setTimeout(poll, 1000 * pending.interval);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [auth, pending, restore, fail]);

  async function signOut() {
    if (!auth) return;
    const result = await auth.signOut();
    if (!result.success) throw new Error('cloud_signout_failed');
    generation.current++;
    setSession(null);
    setPassword('');
    setPending(null);
    setProvider(null);
    setError(null);
    window.location.hash = '';
    setPhase('signed_out');
  }
  async function login(trustedDevice: boolean) {
    if (!auth) return;
    const revision = ++generation.current;
    setPhase('signing_in');
    setError(null);
    try {
      const result = await auth.loginWithPassword({
        apiBaseUrl: origin,
        username: email,
        password,
        trustedDevice,
      });
      if (revision !== generation.current) return;
      if (result.status === 'password_change_required') setPhase(result.status);
      else await restore(revision);
    } catch (cause) {
      if (revision === generation.current) fail(cause);
    }
  }
  const openSso = (attempt: NativeDeviceAuthorizationOpened) =>
    window.__MEMSTACK_DESKTOP__?.core?.invoke?.('open_device_authorization_url', {
      url: attempt.authorizationUrl,
      deviceAuthorizationBaseUrl: DEFAULT_CONFIG.deviceAuthorizationBaseUrl,
      expectedUserCode: attempt.userCode,
    });
  if (phase === 'signed_in')
    return (
      <FullWorkbench
        key={session?.user.userId ?? 'select-scope'}
        session={session}
        reload={restore}
        signOut={() => void signOut().catch(fail)}
      />
    );
  if (phase === 'password_change_required')
    return (
      <ForcePasswordChangeScreen
        busy={false}
        error={error}
        onSignOut={() => void signOut().catch(fail)}
        onSubmit={(currentPassword, newPassword) => {
          void auth
            ?.forceChangePassword({ currentPassword, newPassword })
            .then(() => restore())
            .catch((cause) => setError(String(cause)));
        }}
      />
    );
  return (
    <LoginScreen
      auth={{
        status: phase === 'loading' || phase === 'signing_in' ? 'signing_in' : 'signed_out',
        error,
      }}
      cloudApiBaseUrl={origin}
      onCloudApiBaseUrlChange={setOrigin}
      email={email}
      password={password}
      onEmailChange={setEmail}
      onPasswordChange={setPassword}
      onEmailLogin={(trusted) => void login(trusted)}
      nativeOAuthProviders={providers}
      nativeOAuthPendingProvider={provider}
      onNativeOAuth={(id, trustedDevice) => {
        setProvider(id);
        void oauth
          ?.begin({
            apiBaseUrl: origin,
            provider: id,
            trustedDevice,
            resumeRoute: window.location.hash.slice(1) || '/',
          })
          .catch((cause) => {
            setProvider(null);
            fail(cause);
          });
      }}
      workspaceSso={pending && { ...pending, openError: error }}
      onOpenWorkspaceSso={() => {
        if (pending) void openSso(pending)?.catch((cause) => setError(String(cause)));
      }}
      onCancelWorkspaceSso={() => {
        if (pending)
          void auth
            ?.cancelDeviceAuthorization(pending.attemptId)
            .catch((cause) => setError(String(cause)));
        generation.current++;
        setPending(null);
        setPhase('signed_out');
      }}
      onWorkspaceSso={(trustedDevice) => {
        const revision = ++generation.current;
        setPhase('signing_in');
        setError(null);
        void auth
          ?.beginDeviceAuthorization({
            apiBaseUrl: origin,
            deviceAuthorizationBaseUrl: DEFAULT_CONFIG.deviceAuthorizationBaseUrl,
            trustedDevice,
          })
          .then(async (value) => {
            if (generation.current !== revision) {
              await auth.cancelDeviceAuthorization(value.attemptId);
              return;
            }
            setPending(value);
            await openSso(value)?.catch((cause) => setError(String(cause)));
          })
          .catch((cause) => {
            if (generation.current === revision) fail(cause);
          });
      }}
    />
  );
}
