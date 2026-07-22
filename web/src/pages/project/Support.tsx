import React, { useEffect, useState, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { message } from 'antd';
import {
  MessageSquare,
  Send,
  ExternalLink,
  FileText,
  BookOpen,
  HelpCircle,
  Plus,
  ChevronLeft,
  ChevronRight,
  Loader2,
} from 'lucide-react';

import { formatDateTime } from '@/utils/date';

import api from '../../services/api';
import { useTenantStore } from '../../stores/tenant';
import { confirmAction } from '../../utils/confirmAction';
import { logger } from '../../utils/logger';

interface SupportTicket {
  id: string;
  tenant_id: string | null;
  subject: string;
  message: string;
  priority: string;
  status: string;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

interface SupportTicketResponse {
  id: string;
  tenant_id: string | null;
  subject: string;
  message: string;
  priority: string;
  status: string;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

interface SupportTicketsResponse {
  tickets: SupportTicketResponse[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

const TICKETS_PAGE_SIZE = 25;

export const Support: React.FC = () => {
  const { t } = useTranslation();
  const { currentTenant } = useTenantStore();
  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [currentPage, setCurrentPage] = useState(0);
  const [totalTickets, setTotalTickets] = useState(0);
  const [hasMoreTickets, setHasMoreTickets] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showNewTicket, setShowNewTicket] = useState(false);

  // New ticket form
  const [subject, setSubject] = useState('');
  const [ticketMessage, setTicketMessage] = useState('');
  const [priority, setPriority] = useState('medium');

  const loadTickets = useCallback(
    async (pageToLoad: number) => {
      if (!currentTenant) {
        setTickets([]);
        setTotalTickets(0);
        setHasMoreTickets(false);
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      setLoadError(null);
      try {
        const data = await api.get<SupportTicketsResponse>('/support/tickets', {
          params: {
            tenant_id: currentTenant.id,
            limit: TICKETS_PAGE_SIZE,
            offset: pageToLoad * TICKETS_PAGE_SIZE,
          },
        });
        setTickets(data.tickets as SupportTicket[]);
        setTotalTickets(data.total);
        setHasMoreTickets(data.has_more);
      } catch (error) {
        logger.error('[Support] Failed to load support tickets:', error);
        setLoadError(t('project.support.messages.load_fail', 'Failed to load support tickets.'));
      } finally {
        setIsLoading(false);
      }
    },
    [currentTenant, t]
  );

  useEffect(() => {
    void loadTickets(currentPage);
  }, [currentPage, loadTickets]);

  useEffect(() => {
    setCurrentPage(0);
  }, [currentTenant?.id]);

  const handleSubmitTicket = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!subject.trim() || !ticketMessage.trim()) {
      message.warning(
        t('project.support.form.required_error', 'Subject and message are required.')
      );
      return;
    }

    setIsSubmitting(true);
    try {
      await api.post('/support/tickets', {
        tenant_id: currentTenant?.id,
        subject,
        message: ticketMessage,
        priority,
      });

      // Reset form
      setSubject('');
      setTicketMessage('');
      setPriority('medium');
      setShowNewTicket(false);

      setCurrentPage(0);
      await loadTickets(0);

      message.success(t('project.support.messages.submit_success'));
    } catch (error) {
      logger.error('[Support] Failed to submit ticket:', error);
      message.error(t('project.support.messages.submit_fail'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCloseTicket = async (ticketId: string) => {
    if (!(await confirmAction(t('project.support.tickets.close_confirm')))) return;

    try {
      await api.post(`/support/tickets/${ticketId}/close`);
      message.success(t('project.support.messages.close_success', 'Ticket closed'));
      await loadTickets(currentPage);
    } catch (error) {
      logger.error('[Support] Failed to close ticket:', error);
      message.error(t('project.support.messages.close_fail'));
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'open':
        return 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-400';
      case 'in_progress':
        return 'bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-400';
      case 'resolved':
        return 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-800 dark:text-yellow-400';
      case 'closed':
        return 'bg-gray-100 dark:bg-gray-900/30 text-gray-800 dark:text-gray-400';
      default:
        return 'bg-gray-100 dark:bg-gray-900/30 text-gray-800 dark:text-gray-400';
    }
  };

  const getStatusText = (status: string) => {
    const statusMap: Record<string, string> = {
      open: t('project.support.tickets.status.open'),
      in_progress: t('project.support.tickets.status.in_progress'),
      resolved: t('project.support.tickets.status.resolved'),
      closed: t('project.support.tickets.status.closed'),
    };
    return statusMap[status] || status;
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'low':
        return 'text-gray-600 dark:text-gray-400';
      case 'medium':
        return 'text-yellow-600 dark:text-yellow-400';
      case 'high':
        return 'text-orange-600 dark:text-orange-400';
      case 'urgent':
        return 'text-red-600 dark:text-red-400';
      default:
        return 'text-gray-600 dark:text-gray-400';
    }
  };

  const getPriorityText = (priority: string) => {
    const priorityMap: Record<string, string> = {
      low: t('project.support.tickets.priority.low'),
      medium: t('project.support.tickets.priority.medium'),
      high: t('project.support.tickets.priority.high'),
      urgent: t('project.support.tickets.priority.urgent'),
    };
    return priorityMap[priority] || priority;
  };

  const totalPages = Math.max(1, Math.ceil(totalTickets / TICKETS_PAGE_SIZE));
  const pageStart = totalTickets === 0 ? 0 : currentPage * TICKETS_PAGE_SIZE + 1;
  const pageEnd = Math.min(totalTickets, (currentPage + 1) * TICKETS_PAGE_SIZE);

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
          {t('project.support.title')}
        </h1>
        <p className="text-gray-600 dark:text-gray-400">{t('project.support.subtitle')}</p>
      </div>

      {/* Quick Links */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <a
          href="https://docs.memstack.ai"
          target="_blank"
          rel="noopener noreferrer"
          className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6 hover:shadow-md transition-shadow"
        >
          <div className="flex items-center gap-3 mb-3">
            <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
              <BookOpen className="h-5 w-5 text-blue-600 dark:text-blue-400" />
            </div>
            <h3 className="font-semibold text-gray-900 dark:text-white">
              {t('project.support.docs.title')}
            </h3>
          </div>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
            {t('project.support.docs.desc')}
          </p>
          <div className="flex items-center gap-1 text-sm text-blue-600 dark:text-blue-400">
            {t('project.support.docs.link')} <ExternalLink className="h-3 w-3" />
          </div>
        </a>

        <a
          href="https://docs.memstack.ai/api"
          target="_blank"
          rel="noopener noreferrer"
          className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6 hover:shadow-md transition-shadow"
        >
          <div className="flex items-center gap-3 mb-3">
            <div className="p-2 bg-green-100 dark:bg-green-900/30 rounded-lg">
              <FileText className="h-5 w-5 text-green-600 dark:text-green-400" />
            </div>
            <h3 className="font-semibold text-gray-900 dark:text-white">
              {t('project.support.api.title')}
            </h3>
          </div>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
            {t('project.support.api.desc')}
          </p>
          <div className="flex items-center gap-1 text-sm text-green-600 dark:text-green-400">
            {t('project.support.api.link')} <ExternalLink className="h-3 w-3" />
          </div>
        </a>

        <a
          href="https://docs.memstack.ai/faq"
          target="_blank"
          rel="noopener noreferrer"
          className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6 hover:shadow-md transition-shadow"
        >
          <div className="flex items-center gap-3 mb-3">
            <div className="p-2 bg-purple-100 dark:bg-purple-900/30 rounded-lg">
              <HelpCircle className="h-5 w-5 text-purple-600 dark:text-purple-400" />
            </div>
            <h3 className="font-semibold text-gray-900 dark:text-white">
              {t('project.support.faq.title')}
            </h3>
          </div>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
            {t('project.support.faq.desc')}
          </p>
          <div className="flex items-center gap-1 text-sm text-purple-600 dark:text-purple-400">
            {t('project.support.faq.link')} <ExternalLink className="h-3 w-3" />
          </div>
        </a>
      </div>

      {/* Create Ticket Button */}
      <div className="mb-6">
        {!showNewTicket ? (
          <button
            type="button"
            onClick={() => {
              setShowNewTicket(true);
            }}
            className="flex items-center gap-2 bg-blue-600 dark:bg-blue-500 hover:bg-blue-700 dark:hover:bg-blue-600 text-white px-4 py-2 rounded-lg font-medium transition-colors"
          >
            <Plus className="h-4 w-4" />
            {t('project.support.create_ticket')}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => {
              setShowNewTicket(false);
            }}
            className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
          >
            {t('project.support.cancel')}
          </button>
        )}
      </div>

      {/* New Ticket Form */}
      {showNewTicket && (
        <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6 mb-6">
          <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
            {t('project.support.create_ticket')}
          </h2>
          <form
            onSubmit={(event) => {
              void handleSubmitTicket(event);
            }}
          >
            <div className="mb-4">
              <label
                htmlFor="ticket-subject"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
              >
                {t('project.support.form.subject')}
              </label>
              <input
                id="ticket-subject"
                name="subject"
                type="text"
                value={subject}
                onChange={(e) => {
                  setSubject(e.target.value);
                }}
                className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                placeholder={t('project.support.form.subject_placeholder')}
                required
              />
            </div>

            <div className="mb-4">
              <label
                htmlFor="ticket-priority"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
              >
                {t('project.support.form.priority')}
              </label>
              <select
                id="ticket-priority"
                name="priority"
                value={priority}
                onChange={(e) => {
                  setPriority(e.target.value);
                }}
                className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
              >
                <option value="low">{t('project.support.form.priority_options.low')}</option>
                <option value="medium">{t('project.support.form.priority_options.medium')}</option>
                <option value="high">{t('project.support.form.priority_options.high')}</option>
                <option value="urgent">{t('project.support.form.priority_options.urgent')}</option>
              </select>
            </div>

            <div className="mb-4">
              <label
                htmlFor="ticket-message"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
              >
                {t('project.support.form.message')}
              </label>
              <textarea
                id="ticket-message"
                name="message"
                value={ticketMessage}
                onChange={(e) => {
                  setTicketMessage(e.target.value);
                }}
                rows={6}
                className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none resize-none"
                placeholder={t('project.support.form.message_placeholder')}
                required
              />
            </div>

            <div className="flex gap-3">
              <button
                type="submit"
                disabled={isSubmitting}
                className="flex items-center gap-2 bg-blue-600 dark:bg-blue-500 hover:bg-blue-700 dark:hover:bg-blue-600 disabled:bg-gray-400 text-white px-4 py-2 rounded-lg font-medium transition-colors"
              >
                {isSubmitting ? (
                  <Loader2
                    className="h-4 w-4 animate-spin motion-reduce:animate-none"
                    aria-hidden="true"
                  />
                ) : (
                  <Send className="h-4 w-4" aria-hidden="true" />
                )}
                {isSubmitting
                  ? t('project.support.form.submitting')
                  : t('project.support.form.submit')}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowNewTicket(false);
                }}
                className="px-4 py-2 border border-gray-300 dark:border-slate-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors"
              >
                {t('project.support.cancel')}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Tickets List */}
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
          {t('project.support.tickets.title')}
        </h2>

        {isLoading ? (
          <div
            className="flex items-center justify-center h-32"
            role="status"
            aria-label={t('common.loading', 'Loading…')}
          >
            <div className="animate-spin motion-reduce:animate-none rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
          </div>
        ) : loadError ? (
          <div
            className="flex flex-col items-center gap-3 rounded-lg border border-red-200 bg-red-50 p-8 text-center dark:border-red-900/50 dark:bg-red-900/20"
            role="alert"
          >
            <p className="text-sm text-red-700 dark:text-red-400">{loadError}</p>
            <button
              type="button"
              onClick={() => {
                void loadTickets(currentPage);
              }}
              className="inline-flex h-9 items-center rounded-md bg-slate-950 px-4 text-sm font-medium text-slate-50 transition-colors hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950/20 dark:bg-slate-50 dark:text-slate-950 dark:hover:bg-slate-200 dark:focus-visible:ring-slate-50/20"
            >
              {t('common.retry', 'Retry')}
            </button>
          </div>
        ) : tickets.length === 0 ? (
          <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-8 text-center">
            <MessageSquare className="h-12 w-12 mx-auto mb-3 opacity-50 text-gray-400" />
            <p className="text-gray-600 dark:text-gray-400">{t('project.support.tickets.empty')}</p>
            <p className="text-sm text-gray-500 dark:text-gray-500 mt-1">
              {t('project.support.tickets.empty_desc')}
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {totalTickets > TICKETS_PAGE_SIZE && (
              <div className="flex flex-col gap-3 rounded-lg border border-gray-200 bg-white p-3 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:flex-row sm:items-center sm:justify-between">
                <span className="text-sm text-gray-600 dark:text-gray-400">
                  {t('project.support.tickets.pagination_summary', {
                    start: pageStart,
                    end: pageEnd,
                    total: totalTickets,
                  })}
                </span>
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      setCurrentPage((page) => Math.max(0, page - 1));
                    }}
                    disabled={currentPage === 0 || isLoading}
                    className="inline-flex h-9 items-center gap-1 rounded-md border border-gray-300 bg-white px-3 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-gray-300 dark:hover:bg-slate-800"
                  >
                    <ChevronLeft className="h-4 w-4" />
                    {t('common.actions.previous')}
                  </button>
                  <span className="min-w-24 text-center text-sm text-gray-500 dark:text-gray-400">
                    {t('common.pagination.page_info', {
                      page: currentPage + 1,
                      total: totalPages,
                    })}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setCurrentPage((page) => page + 1);
                    }}
                    disabled={!hasMoreTickets || isLoading}
                    className="inline-flex h-9 items-center gap-1 rounded-md border border-gray-300 bg-white px-3 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-gray-300 dark:hover:bg-slate-800"
                  >
                    {t('common.actions.next')}
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )}

            {tickets.map((ticket) => (
              <div
                key={ticket.id}
                className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1 min-w-0">
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-1 break-words">
                      {ticket.subject}
                    </h3>
                    <div className="flex items-center gap-3 text-sm">
                      <span
                        className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(ticket.status)}`}
                      >
                        {getStatusText(ticket.status)}
                      </span>
                      <span className={`text-sm font-medium ${getPriorityColor(ticket.priority)}`}>
                        {t('project.support.form.priority')}: {getPriorityText(ticket.priority)}
                      </span>
                      <span className="text-gray-500 dark:text-gray-400">
                        {t('project.support.tickets.created_at')}{' '}
                        {formatDateTime(ticket.created_at)}
                      </span>
                    </div>
                  </div>
                  {ticket.status === 'open' && (
                    <button
                      type="button"
                      onClick={() => {
                        void handleCloseTicket(ticket.id);
                      }}
                      className="shrink-0 rounded-md px-2 py-1 text-sm text-gray-600 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-slate-800 dark:hover:text-white"
                    >
                      {t('project.support.tickets.close')}
                    </button>
                  )}
                </div>

                <div className="bg-gray-50 dark:bg-slate-800 rounded-lg p-3 mb-3">
                  <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                    {ticket.message}
                  </p>
                </div>

                {ticket.resolved_at && (
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {t('project.support.tickets.resolved_at')} {formatDateTime(ticket.resolved_at)}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
