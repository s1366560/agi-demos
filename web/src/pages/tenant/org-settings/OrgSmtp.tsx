import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Eye, EyeOff, Loader2, Mail, MailCheck, RefreshCcw, Send, Trash2 } from 'lucide-react';

import { useSmtpConfig, useSmtpLoading, useSmtpActions } from '@/stores/smtp';
import { useTenantStore } from '@/stores/tenant';

import { smtpService } from '@/services/smtpService';
import type { SmtpConfigCreate } from '@/services/smtpService';

import { useLazyMessage, LazyPopconfirm, LazySpin } from '@/components/ui/lazyAntd';

export const OrgSmtp: React.FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const currentTenant = useTenantStore((s) => s.currentTenant);

  const config = useSmtpConfig();
  const isLoading = useSmtpLoading();
  const { fetchConfig } = useSmtpActions();

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const [host, setHost] = useState('');
  const [port, setPort] = useState(465);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [fromEmail, setFromEmail] = useState('');
  const [fromName, setFromName] = useState('');
  const [useTls, setUseTls] = useState(true);

  const [recipientEmail, setRecipientEmail] = useState('');

  useEffect(() => {
    if (currentTenant) {
      void fetchConfig(currentTenant.id);
    }
  }, [currentTenant, fetchConfig]);

  useEffect(() => {
    if (config) {
      setHost(config.smtp_host);
      setPort(config.smtp_port);
      setUsername(config.smtp_username);
      setPassword('');
      setFromEmail(config.from_email);
      setFromName(config.from_name || '');
      setUseTls(config.use_tls);
    } else {
      setHost('');
      setPort(465);
      setUsername('');
      setPassword('');
      setFromEmail('');
      setFromName('');
      setUseTls(true);
    }
  }, [config]);

  const handleSave = useCallback(async () => {
    if (!currentTenant) return;
    if (!host || !port || !username || !fromEmail) {
      message?.error(t('common.requiredFields', 'Please fill all required fields'));
      return;
    }

    if (!config && !password) {
      message?.error(
        t('tenant.orgSettings.smtp.passwordRequired', 'Password is required for new config')
      );
      return;
    }

    setIsSubmitting(true);
    try {
      const data: SmtpConfigCreate = {
        smtp_host: host,
        smtp_port: port,
        smtp_username: username,
        smtp_password: password || '',
        from_email: fromEmail,
        from_name: fromName || null,
        use_tls: useTls,
      };

      await smtpService.upsertConfig(currentTenant.id, data);
      await fetchConfig(currentTenant.id);
      setPassword('');
      message?.success(
        t('tenant.orgSettings.smtp.saveSuccess', 'SMTP configuration saved successfully')
      );
    } catch (_err) {
      message?.error(t('tenant.orgSettings.smtp.saveError', 'Failed to save SMTP configuration'));
    } finally {
      setIsSubmitting(false);
    }
  }, [
    currentTenant,
    host,
    port,
    username,
    password,
    fromEmail,
    fromName,
    useTls,
    config,
    fetchConfig,
    message,
    t,
  ]);

  const handleTest = useCallback(async () => {
    if (!currentTenant) return;
    if (!recipientEmail) {
      message?.error(
        t('tenant.orgSettings.smtp.recipientRequired', 'Recipient email is required for testing')
      );
      return;
    }

    setIsTesting(true);
    try {
      await smtpService.testSmtp(currentTenant.id, { recipient_email: recipientEmail });
      message?.success(t('tenant.orgSettings.smtp.testSuccess', 'Test email sent successfully'));
      setRecipientEmail('');
    } catch (_err) {
      message?.error(t('tenant.orgSettings.smtp.testError', 'Failed to send test email'));
    } finally {
      setIsTesting(false);
    }
  }, [currentTenant, recipientEmail, message, t]);

  const handleDelete = useCallback(async () => {
    if (!currentTenant || !config) return;

    setIsSubmitting(true);
    try {
      await smtpService.deleteConfig(currentTenant.id);
      await fetchConfig(currentTenant.id);
      message?.success(
        t('tenant.orgSettings.smtp.deleteSuccess', 'SMTP configuration deleted successfully')
      );
    } catch (_err) {
      message?.error(
        t('tenant.orgSettings.smtp.deleteError', 'Failed to delete SMTP configuration')
      );
    } finally {
      setIsSubmitting(false);
    }
  }, [currentTenant, config, fetchConfig, message, t]);

  if (!currentTenant) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-slate-500">{t('common.noTenant', 'No tenant selected')}</p>
      </div>
    );
  }

  if (isLoading && !config) {
    return (
      <div className="flex items-center justify-center py-20">
        <LazySpin size="large" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            {t('tenant.orgSettings.smtp.title', 'SMTP Configuration')}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t(
              'tenant.orgSettings.smtp.description',
              'Configure email server settings for sending notifications'
            )}
          </p>
        </div>
        {config && (
          <LazyPopconfirm
            title={t(
              'tenant.orgSettings.smtp.deleteConfirm',
              'Delete the SMTP configuration? Notification emails will no longer be sent.'
            )}
            onConfirm={() => void handleDelete()}
            okText={t('common.delete', 'Delete')}
            cancelText={t('common.cancel', 'Cancel')}
          >
            <button
              type="button"
              disabled={isSubmitting}
              className="inline-flex items-center gap-2 px-4 py-2 border border-red-200 text-red-600 dark:border-red-900/50 dark:text-red-400 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors text-sm font-medium"
            >
              <Trash2 size={16} />
              {t('common.delete', 'Delete')}
            </button>
          </LazyPopconfirm>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900 p-6">
        <h3 className="mb-6 flex items-center gap-2 text-base font-semibold text-slate-900 dark:text-slate-100">
          <Mail size={16} className="text-primary" />
          {t('tenant.orgSettings.smtp.serverSettings', 'Server Settings')}
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-4xl">
          <div>
            <label
              htmlFor="smtp-host"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
            >
              {t('tenant.orgSettings.smtp.host', 'SMTP Host')} *
            </label>
            <input
              id="smtp-host"
              type="text"
              value={host}
              onChange={(e) => {
                setHost(e.target.value);
              }}
              autoComplete="off"
              spellCheck={false}
              className="w-full rounded-lg border border-slate-300 bg-slate-100 px-4 py-2.5 text-slate-900 outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              placeholder={t('tenant.orgSettings.smtp.hostPlaceholder')}
            />
          </div>

          <div>
            <label
              htmlFor="smtp-port"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
            >
              {t('tenant.orgSettings.smtp.port', 'SMTP Port')} *
            </label>
            <input
              id="smtp-port"
              type="number"
              value={port}
              onChange={(e) => {
                const parsed = parseInt(e.target.value, 10);
                setPort(Number.isNaN(parsed) ? 0 : parsed);
              }}
              className="w-full rounded-lg border border-slate-300 bg-slate-100 px-4 py-2.5 text-slate-900 outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              placeholder={t('tenant.orgSettings.smtp.portPlaceholder')}
            />
          </div>

          <div>
            <label
              htmlFor="smtp-username"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
            >
              {t('tenant.orgSettings.smtp.username', 'Username')} *
            </label>
            <input
              id="smtp-username"
              type="text"
              value={username}
              onChange={(e) => {
                setUsername(e.target.value);
              }}
              autoComplete="off"
              spellCheck={false}
              className="w-full rounded-lg border border-slate-300 bg-slate-100 px-4 py-2.5 text-slate-900 outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              placeholder={t('tenant.orgSettings.smtp.usernamePlaceholder')}
            />
          </div>

          <div>
            <label
              htmlFor="smtp-password"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
            >
              {t('tenant.orgSettings.smtp.password', 'Password')} {config ? '' : '*'}
            </label>
            <div className="relative">
              <input
                id="smtp-password"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                }}
                autoComplete="new-password"
                spellCheck={false}
                className="w-full rounded-lg border border-slate-300 bg-slate-100 px-4 py-2.5 pr-10 text-slate-900 outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                placeholder={
                  config
                    ? config.smtp_password_masked
                    : t('tenant.orgSettings.smtp.passwordPlaceholder', 'Enter password')
                }
              />
              <button
                type="button"
                className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                aria-label={showPassword ? t('common.hidePassword') : t('common.showPassword')}
                title={showPassword ? t('common.hidePassword') : t('common.showPassword')}
                onClick={() => {
                  setShowPassword(!showPassword);
                }}
              >
                {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
              </button>
            </div>
            {config && (
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                {t('tenant.orgSettings.smtp.passwordHint', 'Leave empty to keep existing password')}
              </p>
            )}
          </div>

          <div>
            <label
              htmlFor="from-email"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
            >
              {t('tenant.orgSettings.smtp.fromEmail', 'From Email')} *
            </label>
            <input
              id="from-email"
              type="email"
              value={fromEmail}
              onChange={(e) => {
                setFromEmail(e.target.value);
              }}
              autoComplete="email"
              spellCheck={false}
              className="w-full rounded-lg border border-slate-300 bg-slate-100 px-4 py-2.5 text-slate-900 outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              placeholder={t('tenant.orgSettings.smtp.fromEmailPlaceholder')}
            />
          </div>

          <div>
            <label
              htmlFor="from-name"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
            >
              {t('tenant.orgSettings.smtp.fromName', 'From Name')}
            </label>
            <input
              id="from-name"
              type="text"
              value={fromName}
              onChange={(e) => {
                setFromName(e.target.value);
              }}
              className="w-full rounded-lg border border-slate-300 bg-slate-100 px-4 py-2.5 text-slate-900 outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              placeholder={t('tenant.orgSettings.smtp.fromNamePlaceholder')}
            />
          </div>

          <div className="col-span-1 md:col-span-2 flex items-center gap-2 mt-2">
            <input
              id="use-tls"
              type="checkbox"
              checked={useTls}
              onChange={(e) => {
                setUseTls(e.target.checked);
              }}
              className="w-4 h-4 rounded border-slate-300 text-primary focus:ring-primary"
            />
            <label htmlFor="use-tls" className="text-sm text-slate-700 dark:text-slate-300">
              {t('tenant.orgSettings.smtp.useTls', 'Use TLS/SSL')}
            </label>
          </div>
        </div>

        <div className="mt-8 pt-6 border-t border-slate-200 dark:border-slate-700">
          <button
            type="button"
            onClick={() => {
              void handleSave();
            }}
            disabled={isSubmitting}
            className="flex items-center gap-2 rounded-lg bg-primary px-6 py-2.5 font-medium text-slate-50 transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isSubmitting && (
              <Loader2 size={20} className="animate-spin motion-reduce:animate-none" />
            )}
            {t('common.save', 'Save')}
          </button>
        </div>
      </div>

      {config && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900 p-6">
          <h3 className="mb-2 flex items-center gap-2 text-base font-semibold text-slate-900 dark:text-slate-100">
            <Send size={16} className="text-green-600" />
            {t('tenant.orgSettings.smtp.testTitle', 'Test Configuration')}
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 mb-6">
            {t(
              'tenant.orgSettings.smtp.testDescription',
              'Send a test email to verify your SMTP settings.'
            )}
          </p>

          <div className="flex flex-col sm:flex-row gap-4 max-w-2xl">
            <div className="flex-1">
              <input
                type="email"
                value={recipientEmail}
                onChange={(e) => {
                  setRecipientEmail(e.target.value);
                }}
                aria-label={t('tenant.orgSettings.smtp.recipientEmail', 'Recipient email address')}
                autoComplete="email"
                spellCheck={false}
                className="w-full rounded-lg border border-slate-300 bg-slate-100 px-4 py-2.5 text-slate-900 outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                placeholder={t('tenant.orgSettings.smtp.recipientEmail', 'Recipient email address')}
              />
            </div>
            <button
              type="button"
              onClick={() => {
                void handleTest();
              }}
              disabled={isTesting || !recipientEmail}
              className="flex items-center gap-2 whitespace-nowrap rounded-lg bg-slate-100 px-6 py-2.5 font-medium text-slate-700 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
            >
              {isTesting ? (
                <RefreshCcw size={20} className="animate-spin motion-reduce:animate-none" />
              ) : (
                <MailCheck size={20} />
              )}
              {t('tenant.orgSettings.smtp.sendTest', 'Send Test')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default OrgSmtp;
