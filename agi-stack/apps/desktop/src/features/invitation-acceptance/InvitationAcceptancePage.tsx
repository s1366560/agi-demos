import { useCallback, useEffect, useRef, useState } from 'react';
import {
  CheckCircledIcon,
  EnvelopeClosedIcon,
  ExclamationTriangleIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import {
  InvitationAcceptanceError,
  type InvitationAcceptanceClient,
} from './invitationAcceptanceClient';
import {
  invitationIsExpired,
  type AcceptedInvitation,
  type InvitationVerification,
} from './invitationAcceptanceModel';
import './InvitationAcceptancePage.css';

export type InvitationAcceptancePageProps = Readonly<{
  client: InvitationAcceptanceClient;
  token: string;
  authenticated(): boolean;
  accountEmail(): string;
  onRequireSignIn(): void;
  onAccepted(invitation: AcceptedInvitation, signal: AbortSignal): Promise<void> | void;
  onNavigateHome(): void;
}>;

type PageState = 'loading' | 'ready' | 'accepting' | 'accepted' | 'error';

export function InvitationAcceptancePage(props: InvitationAcceptancePageProps) {
  const { t } = useI18n();
  const [state, setState] = useState<PageState>('loading');
  const [details, setDetails] = useState<InvitationVerification | null>(null);
  const [accepted, setAccepted] = useState<AcceptedInvitation | null>(null);
  const [reasonCode, setReasonCode] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);

  const verify = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setState('loading');
    setReasonCode(null);
    try {
      const nextDetails = await props.client.verify(props.token, {
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (invitationIsExpired(nextDetails.expires_at)) {
        setReasonCode('invitation_token_expired');
        setState('error');
        return;
      }
      setDetails(nextDetails);
      setState('ready');
    } catch (error) {
      if (controller.signal.aborted) return;
      setReasonCode(
        error instanceof InvitationAcceptanceError
          ? error.reasonCode
          : 'invitation_verification_failed',
      );
      setState('error');
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
    }
  }, [props.client, props.token]);

  useEffect(() => {
    void verify();
    return () => requestRef.current?.abort();
  }, [verify]);

  const accept = async () => {
    if (state === 'accepting' || !props.authenticated()) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setState('accepting');
    setReasonCode(null);
    try {
      const invitation = await props.client.accept(props.token, {
        signal: controller.signal,
      });
      await props.onAccepted(invitation, controller.signal);
      if (controller.signal.aborted) return;
      setAccepted(invitation);
      setState('accepted');
    } catch (error) {
      if (controller.signal.aborted) return;
      setReasonCode(
        error instanceof InvitationAcceptanceError
          ? error.reasonCode
          : 'invitation_acceptance_failed',
      );
      setState('error');
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
    }
  };

  if (state === 'loading') {
    return <section className="invitation-acceptance-page" aria-busy="true">
      <span className="invitation-acceptance-spinner" />
      <h1>{t('invitationAcceptance.loading.title')}</h1>
      <p>{t('invitationAcceptance.loading.description')}</p>
    </section>;
  }

  if (state === 'accepted' && accepted) {
    return <section className="invitation-acceptance-page invitation-acceptance-success">
      <CheckCircledIcon aria-hidden="true" />
      <h1>{t('invitationAcceptance.accepted.title')}</h1>
      <p>{t('invitationAcceptance.accepted.description')}</p>
      <button type="button" onClick={props.onNavigateHome} autoFocus>
        {t('invitationAcceptance.openTenant')}
      </button>
    </section>;
  }

  if (state === 'error') {
    const key = reasonCode
      ? `invitationAcceptance.error.${reasonCode}`
      : 'invitationAcceptance.error.invitation_verification_failed';
    return <section className="invitation-acceptance-page invitation-acceptance-error" role="alert">
      <ExclamationTriangleIcon aria-hidden="true" />
      <h1>{t('invitationAcceptance.error.title')}</h1>
      <p>{t(key)}</p>
      {reasonCode ? <code>{reasonCode}</code> : null}
      <div className="invitation-acceptance-actions">
        <button type="button" onClick={() => void verify()}>
          {t('common.retry')}
        </button>
        <button type="button" onClick={props.onNavigateHome}>
          {t('invitationAcceptance.notNow')}
        </button>
      </div>
    </section>;
  }

  const signedIn = props.authenticated();
  const currentEmail = props.accountEmail();
  const emailMismatch = Boolean(
    signedIn && details?.email && currentEmail && details.email !== currentEmail,
  );
  return <section className="invitation-acceptance-page">
    <header>
      <EnvelopeClosedIcon aria-hidden="true" />
      <p>{t('invitationAcceptance.eyebrow')}</p>
      <h1>{t('invitationAcceptance.title')}</h1>
    </header>
    <dl>
      <div><dt>{t('invitationAcceptance.email')}</dt><dd>{details?.email}</dd></div>
      <div><dt>{t('invitationAcceptance.role')}</dt><dd>{details?.role}</dd></div>
      <div><dt>{t('invitationAcceptance.expires')}</dt>
        <dd>{details ? new Date(details.expires_at).toLocaleString() : ''}</dd></div>
    </dl>
    {emailMismatch ? <div className="invitation-acceptance-warning" role="status">
      {t('invitationAcceptance.emailMismatch', {
        invited: details?.email ?? '',
        current: currentEmail,
      })}
    </div> : null}
    <div className="invitation-acceptance-actions">
      {signedIn ? <button
        type="button"
        disabled={state === 'accepting'}
        onClick={() => void accept()}
      >
        {state === 'accepting'
          ? t('invitationAcceptance.accepting')
          : t('invitationAcceptance.accept')}
      </button> : <button type="button" onClick={props.onRequireSignIn}>
        {t('invitationAcceptance.signIn')}
      </button>}
      <button type="button" disabled={state === 'accepting'} onClick={props.onNavigateHome}>
        {t('invitationAcceptance.notNow')}
      </button>
    </div>
  </section>;
}
