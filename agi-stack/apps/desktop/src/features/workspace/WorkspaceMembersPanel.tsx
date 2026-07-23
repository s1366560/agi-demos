import { useEffect, useRef, useState } from 'react';
import { AlertDialog, Button, TextField } from '@radix-ui/themes';
import {
  Cross2Icon,
  PersonIcon,
  PlusIcon,
} from '@radix-ui/react-icons';

import { DesktopApiError } from '../../api/client';
import type { WorkspaceMemberRole } from '../../api/client';
import { useI18n } from '../../i18n';
import type {
  WorkspaceAuthorityCollection,
  WorkspaceMemberSummary,
} from '../../types';
import {
  WORKSPACE_MEMBER_ROLES,
  canManageWorkspaceMembers,
  isWorkspaceMemberRole,
} from './workspaceMembersModel';
import { WorkspaceSettingsScopeChangedError } from './workspaceSettingsModel';
import type { WorkspaceSettingsScope } from './workspaceSettingsModel';
import './WorkspaceMembersPanel.css';

type WorkspaceMembersPanelProps = {
  active: boolean;
  members: WorkspaceAuthorityCollection<WorkspaceMemberSummary>;
  actorUserId: string;
  scope: WorkspaceSettingsScope;
  onAddMember: (
    userId: string,
    role: WorkspaceMemberRole,
    scope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ) => Promise<WorkspaceMemberSummary>;
  onUpdateMemberRole: (
    userId: string,
    role: WorkspaceMemberRole,
    scope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ) => Promise<WorkspaceMemberSummary>;
  onRemoveMember: (
    userId: string,
    scope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ) => Promise<void>;
};

type MemberMutation =
  | { kind: 'add'; userId: string }
  | { kind: 'update'; userId: string }
  | { kind: 'remove'; userId: string };

type MemberFeedback = {
  tone: 'error' | 'success';
  message: string;
};

export function WorkspaceMembersPanel({
  active,
  members,
  actorUserId,
  scope,
  onAddMember,
  onUpdateMemberRole,
  onRemoveMember,
}: WorkspaceMembersPanelProps) {
  const { t } = useI18n();
  const [newUserId, setNewUserId] = useState('');
  const [newRole, setNewRole] = useState<WorkspaceMemberRole>('viewer');
  const [pending, setPending] = useState<MemberMutation | null>(null);
  const [removeCandidate, setRemoveCandidate] =
    useState<WorkspaceMemberSummary | null>(null);
  const [feedback, setFeedback] = useState<MemberFeedback | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const canManage = canManageWorkspaceMembers(members, actorUserId);
  const userIdReady = Boolean(newUserId.trim());

  useEffect(() => {
    requestRef.current?.abort();
    requestRef.current = null;
    setPending(null);
    setRemoveCandidate(null);
    setFeedback(null);
    setNewUserId('');
    setNewRole('viewer');
  }, [
    active,
    scope.contextRevision,
    scope.epoch,
    scope.projectId,
    scope.tenantId,
    scope.workspaceId,
  ]);

  useEffect(
    () => () => {
      requestRef.current?.abort();
    },
    [],
  );

  const addMember = async () => {
    const userId = newUserId.trim();
    if (!active || !canManage || !userId || pending || requestRef.current) return;
    const controller = new AbortController();
    requestRef.current = controller;
    setPending({ kind: 'add', userId });
    setFeedback(null);
    try {
      await onAddMember(userId, newRole, { ...scope }, controller.signal);
      if (controller.signal.aborted || requestRef.current !== controller) return;
      requestRef.current = null;
      setPending(null);
      setNewUserId('');
      setNewRole('viewer');
      setFeedback({
        tone: 'success',
        message: t('workspaceMembers.addSuccess'),
      });
    } catch (error) {
      settleMemberError(error, controller, requestRef, setPending, setFeedback, t);
    }
  };

  const updateMemberRole = async (
    member: WorkspaceMemberSummary,
    role: WorkspaceMemberRole,
  ) => {
    if (
      !active ||
      !canManage ||
      member.role === role ||
      pending ||
      requestRef.current
    ) {
      return;
    }
    const controller = new AbortController();
    requestRef.current = controller;
    setPending({ kind: 'update', userId: member.user_id });
    setFeedback(null);
    try {
      await onUpdateMemberRole(
        member.user_id,
        role,
        { ...scope },
        controller.signal,
      );
      if (controller.signal.aborted || requestRef.current !== controller) return;
      requestRef.current = null;
      setPending(null);
      setFeedback({
        tone: 'success',
        message: t('workspaceMembers.updateSuccess'),
      });
    } catch (error) {
      settleMemberError(error, controller, requestRef, setPending, setFeedback, t);
    }
  };

  const removeMember = async (member: WorkspaceMemberSummary) => {
    if (!active || !canManage || pending || requestRef.current) return;
    const controller = new AbortController();
    requestRef.current = controller;
    setPending({ kind: 'remove', userId: member.user_id });
    setRemoveCandidate(null);
    setFeedback(null);
    try {
      await onRemoveMember(
        member.user_id,
        { ...scope },
        controller.signal,
      );
      if (controller.signal.aborted || requestRef.current !== controller) return;
      requestRef.current = null;
      setPending(null);
      setFeedback({
        tone: 'success',
        message: t('workspaceMembers.removeSuccess'),
      });
    } catch (error) {
      settleMemberError(error, controller, requestRef, setPending, setFeedback, t);
    }
  };

  return (
    <section
      className="workspace-members-panel"
      aria-labelledby="workspace-members-title"
    >
      <header>
        <PersonIcon aria-hidden="true" />
        <div>
          <strong id="workspace-members-title">{t('workspaceMembers.title')}</strong>
          <small>{t('workspaceMembers.description')}</small>
        </div>
      </header>

      {members.status === 'loading' ? (
        <MemberAuthorityState
          state="loading"
          message={t('workspaceMembers.loading')}
        />
      ) : members.status === 'error' ? (
        <MemberAuthorityState
          state="error"
          message={t('workspaceMembers.error')}
          detail={members.error}
        />
      ) : members.status === 'unavailable' ? (
        <MemberAuthorityState
          state="unavailable"
          message={t('workspaceMembers.unavailable')}
        />
      ) : (
        <>
          <div className="workspace-members-add">
            <label>
              <span>{t('workspaceMembers.userId')}</span>
              <TextField.Root
                value={newUserId}
                disabled={!canManage || pending !== null}
                spellCheck={false}
                autoComplete="off"
                placeholder={t('workspaceMembers.userIdPlaceholder')}
                aria-label={t('workspaceMembers.userId')}
                onChange={(event) => {
                  setFeedback(null);
                  setNewUserId(event.currentTarget.value);
                }}
                onKeyDown={(event) => {
                  if (event.key !== 'Enter') return;
                  event.preventDefault();
                  void addMember();
                }}
              />
            </label>
            <label>
              <span>{t('workspaceMembers.role')}</span>
              <select
                value={newRole}
                disabled={!canManage || pending !== null}
                aria-label={t('workspaceMembers.role')}
                onChange={(event) => {
                  const role = event.currentTarget.value;
                  if (isWorkspaceMemberRole(role)) setNewRole(role);
                }}
              >
                {WORKSPACE_MEMBER_ROLES.map((role) => (
                  <option value={role} key={role}>
                    {t(`workspaceMembers.role.${role}`)}
                  </option>
                ))}
              </select>
            </label>
            <Button
              type="button"
              disabled={!canManage || !userIdReady || pending !== null}
              onClick={() => void addMember()}
            >
              <PlusIcon aria-hidden="true" />
              {pending?.kind === 'add'
                ? t('workspaceMembers.adding')
                : t('workspaceMembers.add')}
            </Button>
          </div>

          {!canManage ? (
            <p className="workspace-members-read-only" role="note">
              {t('workspaceMembers.readOnly')}
            </p>
          ) : null}

          {members.items.length === 0 ? (
            <p className="workspace-members-empty">
              {t('workspaceMembers.empty')}
            </p>
          ) : (
            <div className="workspace-members-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">{t('workspaceMembers.member')}</th>
                    <th scope="col">{t('workspaceMembers.role')}</th>
                    <th scope="col">{t('workspaceMembers.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {members.items.map((member) => {
                    const role = isWorkspaceMemberRole(member.role)
                      ? member.role
                      : 'viewer';
                    const rowPending = pending?.userId === member.user_id;
                    return (
                      <tr
                        key={member.id}
                        aria-busy={rowPending}
                      >
                        <td>
                          <strong>{member.user_email ?? member.user_id}</strong>
                          {member.user_email ? <small>{member.user_id}</small> : null}
                        </td>
                        <td>
                          <select
                            value={role}
                            disabled={!canManage || pending !== null}
                            aria-label={t('workspaceMembers.roleForMember', {
                              member: member.user_email ?? member.user_id,
                            })}
                            onChange={(event) => {
                              const nextRole = event.currentTarget.value;
                              if (isWorkspaceMemberRole(nextRole)) {
                                void updateMemberRole(member, nextRole);
                              }
                            }}
                          >
                            {WORKSPACE_MEMBER_ROLES.map((option) => (
                              <option value={option} key={option}>
                                {t(`workspaceMembers.role.${option}`)}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <Button
                            type="button"
                            variant="ghost"
                            color="red"
                            disabled={!canManage || pending !== null}
                            aria-label={t('workspaceMembers.removeMember', {
                              member: member.user_email ?? member.user_id,
                            })}
                            onClick={() => setRemoveCandidate(member)}
                          >
                            <Cross2Icon aria-hidden="true" />
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      <div
        className={`workspace-members-feedback ${feedback?.tone ?? ''}`}
        role={feedback?.tone === 'error' ? 'alert' : 'status'}
        aria-live={feedback?.tone === 'error' ? 'assertive' : 'polite'}
        aria-atomic="true"
      >
        {feedback?.message ?? ''}
      </div>

      <AlertDialog.Root
        open={removeCandidate !== null}
        onOpenChange={(next) => {
          if (!next && pending?.kind !== 'remove') setRemoveCandidate(null);
        }}
      >
        <AlertDialog.Content maxWidth="420px">
          <AlertDialog.Title>
            {t('workspaceMembers.removeTitle')}
          </AlertDialog.Title>
          <AlertDialog.Description>
            {t('workspaceMembers.removeDescription', {
              member:
                removeCandidate?.user_email ??
                removeCandidate?.user_id ??
                t('workspaceMembers.member'),
            })}
          </AlertDialog.Description>
          <div className="workspace-members-confirm-actions">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray">
                {t('common.cancel')}
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button
                color="red"
                onClick={() => {
                  if (removeCandidate) void removeMember(removeCandidate);
                }}
              >
                {t('workspaceMembers.removeConfirm')}
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </section>
  );
}

function MemberAuthorityState({
  state,
  message,
  detail,
}: {
  state: 'loading' | 'error' | 'unavailable';
  message: string;
  detail?: string | null;
}) {
  return (
    <div
      className={`workspace-members-authority ${state}`}
      role={state === 'error' ? 'alert' : 'status'}
    >
      <strong>{message}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function settleMemberError(
  error: unknown,
  controller: AbortController,
  requestRef: React.MutableRefObject<AbortController | null>,
  setPending: React.Dispatch<React.SetStateAction<MemberMutation | null>>,
  setFeedback: React.Dispatch<React.SetStateAction<MemberFeedback | null>>,
  t: (key: string) => string,
) {
  if (controller.signal.aborted || requestRef.current !== controller) return;
  requestRef.current = null;
  setPending(null);
  setFeedback({
    tone: 'error',
    message:
      error instanceof WorkspaceSettingsScopeChangedError
        ? t('workspaceMembers.scopeChanged')
        : error instanceof DesktopApiError && error.status === 403
          ? t('workspaceMembers.permissionDenied')
          : error instanceof DesktopApiError && error.status === 409
            ? t('workspaceMembers.conflict')
            : t('workspaceMembers.genericError'),
  });
}
