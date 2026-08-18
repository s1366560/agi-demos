import type React from 'react';

import { useTranslation } from 'react-i18next';

import { Input, Select } from 'antd';

import { Field, SwitchField } from '@/pages/tenant/WorkspaceSettingsPrimitives';

import { DraftNumberInput } from './DraftNumberInput';

import type { UpdateDraft } from './types';
import type { SettingsDraft } from '@/pages/tenant/workspaceSettingsModel';

const { TextArea } = Input;

export interface DeliveryDroneSectionProps {
  draft: SettingsDraft;
  updateDraft: UpdateDraft;
}

export const DeliveryDroneSection: React.FC<DeliveryDroneSectionProps> = ({
  draft,
  updateDraft,
}) => {
  const { t } = useTranslation();

  return (
    <div className="grid gap-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <Field
          label={t('workspaceSettings.delivery.droneRepo')}
          htmlFor="workspace-delivery-drone-repo"
        >
          <Input
            id="workspace-delivery-drone-repo"
            value={draft.deliveryDroneRepo}
            onChange={(event) => {
              updateDraft('deliveryDroneRepo', event.target.value);
            }}
            placeholder="memstack/my-workspace"
          />
        </Field>
        <Field
          label={t('workspaceSettings.delivery.droneBranch')}
          htmlFor="workspace-delivery-drone-branch"
        >
          <Input
            id="workspace-delivery-drone-branch"
            value={draft.deliveryDroneBranch}
            onChange={(event) => {
              updateDraft('deliveryDroneBranch', event.target.value);
            }}
            placeholder="main"
          />
        </Field>
        <Field
          label={t('workspaceSettings.delivery.dronePollIntervalSeconds')}
          htmlFor="workspace-delivery-drone-poll"
        >
          <DraftNumberInput
            id="workspace-delivery-drone-poll"
            min={1}
            value={draft.deliveryDronePollIntervalSeconds}
            fallback={5}
            onCommit={(next) => {
              updateDraft('deliveryDronePollIntervalSeconds', next);
            }}
          />
        </Field>
        <Field
          label={t('workspaceSettings.delivery.droneServerUrlEnv')}
          htmlFor="workspace-delivery-drone-server-env"
        >
          <Input
            id="workspace-delivery-drone-server-env"
            value={draft.deliveryDroneServerUrlEnv}
            onChange={(event) => {
              updateDraft('deliveryDroneServerUrlEnv', event.target.value);
            }}
            placeholder="DRONE_SERVER_URL"
          />
        </Field>
        <Field
          label={t('workspaceSettings.delivery.droneTokenEnv')}
          htmlFor="workspace-delivery-drone-token-env"
        >
          <Input
            id="workspace-delivery-drone-token-env"
            value={draft.deliveryDroneTokenEnv}
            onChange={(event) => {
              updateDraft('deliveryDroneTokenEnv', event.target.value);
            }}
            placeholder="DRONE_TOKEN"
          />
        </Field>
      </div>

      <div className="grid gap-3 border-t border-border-light pt-4 dark:border-border-dark">
        <div className="text-xs font-semibold text-text-secondary dark:text-text-muted">
          {t('workspaceSettings.delivery.droneDeployStage')}
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <SwitchField
            label={t('workspaceSettings.delivery.droneDeployEnabled')}
            checked={draft.deliveryDroneDeployEnabled}
            onChange={(checked) => {
              updateDraft('deliveryDroneDeployEnabled', checked);
            }}
          />
          <SwitchField
            label={t('workspaceSettings.delivery.droneDeployRequired')}
            checked={draft.deliveryDroneDeployRequired}
            onChange={(checked) => {
              updateDraft('deliveryDroneDeployRequired', checked);
            }}
          />
          <Field
            label={t('workspaceSettings.delivery.droneDeployMode')}
            htmlFor="workspace-delivery-drone-deploy-mode"
          >
            <Select
              id="workspace-delivery-drone-deploy-mode"
              value={draft.deliveryDroneDeployMode}
              onChange={(value) => {
                updateDraft('deliveryDroneDeployMode', value);
              }}
              options={[
                { value: 'docker', label: 'docker' },
                { value: 'kubernetes', label: 'kubernetes' },
                { value: 'cli', label: 'cli' },
              ]}
            />
          </Field>
          <Field
            label={t('workspaceSettings.delivery.droneDeployTarget')}
            htmlFor="workspace-delivery-drone-deploy-target"
          >
            <Input
              id="workspace-delivery-drone-deploy-target"
              value={draft.deliveryDroneDeployTarget}
              onChange={(event) => {
                updateDraft('deliveryDroneDeployTarget', event.target.value);
              }}
              placeholder="staging"
            />
          </Field>
          <Field
            label={t('workspaceSettings.delivery.droneDeployStageName')}
            htmlFor="workspace-delivery-drone-deploy-stage"
          >
            <Input
              id="workspace-delivery-drone-deploy-stage"
              value={draft.deliveryDroneDeployStage}
              onChange={(event) => {
                updateDraft('deliveryDroneDeployStage', event.target.value);
              }}
              placeholder="deploy"
            />
          </Field>
        </div>

        {draft.deliveryDroneDeployMode === 'docker' ? (
          <div className="grid gap-4 lg:grid-cols-3">
            <Field
              label={t('workspaceSettings.delivery.droneDeployDockerImage')}
              htmlFor="workspace-delivery-drone-deploy-docker-image"
            >
              <Input
                id="workspace-delivery-drone-deploy-docker-image"
                value={draft.deliveryDroneDeployDockerImage}
                onChange={(event) => {
                  updateDraft('deliveryDroneDeployDockerImage', event.target.value);
                }}
                placeholder="registry.example.com/app"
              />
            </Field>
            <Field
              label={t('workspaceSettings.delivery.droneDeployDockerRegistry')}
              htmlFor="workspace-delivery-drone-deploy-docker-registry"
            >
              <Input
                id="workspace-delivery-drone-deploy-docker-registry"
                value={draft.deliveryDroneDeployDockerRegistry}
                onChange={(event) => {
                  updateDraft('deliveryDroneDeployDockerRegistry', event.target.value);
                }}
                placeholder="registry.example.com"
              />
            </Field>
            <Field
              label={t('workspaceSettings.delivery.droneDeployDockerContext')}
              htmlFor="workspace-delivery-drone-deploy-docker-context"
            >
              <Input
                id="workspace-delivery-drone-deploy-docker-context"
                value={draft.deliveryDroneDeployDockerContext}
                onChange={(event) => {
                  updateDraft('deliveryDroneDeployDockerContext', event.target.value);
                }}
                placeholder="."
              />
            </Field>
            <Field
              label={t('workspaceSettings.delivery.droneDeployDockerfile')}
              htmlFor="workspace-delivery-drone-deploy-dockerfile"
            >
              <Input
                id="workspace-delivery-drone-deploy-dockerfile"
                value={draft.deliveryDroneDeployDockerfile}
                onChange={(event) => {
                  updateDraft('deliveryDroneDeployDockerfile', event.target.value);
                }}
                placeholder="Dockerfile"
              />
            </Field>
            <Field
              label={t('workspaceSettings.delivery.droneDeployDockerUsernameSecret')}
              htmlFor="workspace-delivery-drone-deploy-docker-username-secret"
            >
              <Input
                id="workspace-delivery-drone-deploy-docker-username-secret"
                value={draft.deliveryDroneDeployDockerUsernameSecret}
                onChange={(event) => {
                  updateDraft('deliveryDroneDeployDockerUsernameSecret', event.target.value);
                }}
                placeholder="docker_username"
              />
            </Field>
            <Field
              label={t('workspaceSettings.delivery.droneDeployDockerPasswordSecret')}
              htmlFor="workspace-delivery-drone-deploy-docker-password-secret"
            >
              <Input
                id="workspace-delivery-drone-deploy-docker-password-secret"
                value={draft.deliveryDroneDeployDockerPasswordSecret}
                onChange={(event) => {
                  updateDraft('deliveryDroneDeployDockerPasswordSecret', event.target.value);
                }}
                placeholder="docker_password"
              />
            </Field>
            <Field
              label={t('workspaceSettings.delivery.droneDeployDockerTags')}
              htmlFor="workspace-delivery-drone-deploy-docker-tags"
            >
              <TextArea
                id="workspace-delivery-drone-deploy-docker-tags"
                value={draft.deliveryDroneDeployDockerTags}
                onChange={(event) => {
                  updateDraft('deliveryDroneDeployDockerTags', event.target.value);
                }}
                className="font-mono text-xs"
                rows={3}
              />
            </Field>
          </div>
        ) : null}

        {draft.deliveryDroneDeployMode === 'kubernetes' ? (
          <div className="grid gap-4 lg:grid-cols-3">
            <Field
              label={t('workspaceSettings.delivery.droneDeployKubernetesNamespace')}
              htmlFor="workspace-delivery-drone-deploy-kubernetes-namespace"
            >
              <Input
                id="workspace-delivery-drone-deploy-kubernetes-namespace"
                value={draft.deliveryDroneDeployKubernetesNamespace}
                onChange={(event) => {
                  updateDraft('deliveryDroneDeployKubernetesNamespace', event.target.value);
                }}
                placeholder="default"
              />
            </Field>
            <Field
              label={t('workspaceSettings.delivery.droneDeployKubeconfigSecret')}
              htmlFor="workspace-delivery-drone-deploy-kubeconfig-secret"
            >
              <Input
                id="workspace-delivery-drone-deploy-kubeconfig-secret"
                value={draft.deliveryDroneDeployKubeconfigSecret}
                onChange={(event) => {
                  updateDraft('deliveryDroneDeployKubeconfigSecret', event.target.value);
                }}
                placeholder="kubeconfig"
              />
            </Field>
            <Field
              label={t('workspaceSettings.delivery.droneDeployKubernetesContext')}
              htmlFor="workspace-delivery-drone-deploy-kubernetes-context"
            >
              <Input
                id="workspace-delivery-drone-deploy-kubernetes-context"
                value={draft.deliveryDroneDeployKubernetesContext}
                onChange={(event) => {
                  updateDraft('deliveryDroneDeployKubernetesContext', event.target.value);
                }}
                placeholder="staging"
              />
            </Field>
            <Field
              label={t('workspaceSettings.delivery.droneDeployKubectlImage')}
              htmlFor="workspace-delivery-drone-deploy-kubectl-image"
            >
              <Input
                id="workspace-delivery-drone-deploy-kubectl-image"
                value={draft.deliveryDroneDeployKubectlImage}
                onChange={(event) => {
                  updateDraft('deliveryDroneDeployKubectlImage', event.target.value);
                }}
                placeholder="bitnami/kubectl:latest"
              />
            </Field>
            <Field
              label={t('workspaceSettings.delivery.droneDeployKubernetesManifestPaths')}
              htmlFor="workspace-delivery-drone-deploy-kubernetes-manifests"
            >
              <TextArea
                id="workspace-delivery-drone-deploy-kubernetes-manifests"
                value={draft.deliveryDroneDeployKubernetesManifestPaths}
                onChange={(event) => {
                  updateDraft('deliveryDroneDeployKubernetesManifestPaths', event.target.value);
                }}
                className="font-mono text-xs"
                rows={3}
              />
            </Field>
          </div>
        ) : null}

        {draft.deliveryDroneDeployMode === 'cli' ? (
          <div className="grid gap-4 lg:grid-cols-2">
            <Field
              label={t('workspaceSettings.delivery.droneDeployCliImage')}
              htmlFor="workspace-delivery-drone-deploy-cli-image"
            >
              <Input
                id="workspace-delivery-drone-deploy-cli-image"
                value={draft.deliveryDroneDeployCliImage}
                onChange={(event) => {
                  updateDraft('deliveryDroneDeployCliImage', event.target.value);
                }}
                placeholder="alpine:3.20"
              />
            </Field>
            <Field
              label={t('workspaceSettings.delivery.droneDeployCliCommands')}
              htmlFor="workspace-delivery-drone-deploy-cli-commands"
            >
              <TextArea
                id="workspace-delivery-drone-deploy-cli-commands"
                value={draft.deliveryDroneDeployCliCommands}
                onChange={(event) => {
                  updateDraft('deliveryDroneDeployCliCommands', event.target.value);
                }}
                className="font-mono text-xs"
                rows={3}
              />
            </Field>
          </div>
        ) : null}
      </div>

      <div className="grid gap-3 border-t border-border-light pt-4 dark:border-border-dark">
        <div className="text-xs font-semibold text-text-secondary dark:text-text-muted">
          {t('workspaceSettings.delivery.droneServerEnvironment')}
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <Field
            label={t('workspaceSettings.delivery.droneServerPort')}
            htmlFor="workspace-delivery-drone-server-port"
          >
            <DraftNumberInput
              id="workspace-delivery-drone-server-port"
              min={1}
              value={draft.deliveryDroneServerPort}
              fallback={8080}
              onCommit={(next) => {
                updateDraft('deliveryDroneServerPort', next);
              }}
            />
          </Field>
          <Field
            label={t('workspaceSettings.delivery.droneServerHost')}
            htmlFor="workspace-delivery-drone-server-host"
          >
            <Input
              id="workspace-delivery-drone-server-host"
              value={draft.deliveryDroneServerHost}
              onChange={(event) => {
                updateDraft('deliveryDroneServerHost', event.target.value);
              }}
              placeholder="localhost:8080"
            />
          </Field>
          <Field
            label={t('workspaceSettings.delivery.droneServerProto')}
            htmlFor="workspace-delivery-drone-server-proto"
          >
            <Input
              id="workspace-delivery-drone-server-proto"
              value={draft.deliveryDroneServerProto}
              onChange={(event) => {
                updateDraft('deliveryDroneServerProto', event.target.value);
              }}
              placeholder="http"
            />
          </Field>
          <Field
            label={t('workspaceSettings.delivery.droneRpcSecretEnv')}
            htmlFor="workspace-delivery-drone-rpc-secret-env"
          >
            <Input
              id="workspace-delivery-drone-rpc-secret-env"
              value={draft.deliveryDroneRpcSecretEnv}
              onChange={(event) => {
                updateDraft('deliveryDroneRpcSecretEnv', event.target.value);
              }}
              placeholder="DRONE_RPC_SECRET"
            />
          </Field>
          <Field
            label={t('workspaceSettings.delivery.droneUserCreate')}
            htmlFor="workspace-delivery-drone-user-create"
          >
            <Input
              id="workspace-delivery-drone-user-create"
              value={draft.deliveryDroneUserCreate}
              onChange={(event) => {
                updateDraft('deliveryDroneUserCreate', event.target.value);
              }}
              placeholder="username:memstack,admin:true"
            />
          </Field>
          <Field
            label={t('workspaceSettings.delivery.droneGithubClientIdEnv')}
            htmlFor="workspace-delivery-drone-github-client-id-env"
          >
            <Input
              id="workspace-delivery-drone-github-client-id-env"
              value={draft.deliveryDroneGithubClientIdEnv}
              onChange={(event) => {
                updateDraft('deliveryDroneGithubClientIdEnv', event.target.value);
              }}
              placeholder="DRONE_GITHUB_CLIENT_ID"
            />
          </Field>
          <Field
            label={t('workspaceSettings.delivery.droneGithubClientSecretEnv')}
            htmlFor="workspace-delivery-drone-github-client-secret-env"
          >
            <Input
              id="workspace-delivery-drone-github-client-secret-env"
              value={draft.deliveryDroneGithubClientSecretEnv}
              onChange={(event) => {
                updateDraft('deliveryDroneGithubClientSecretEnv', event.target.value);
              }}
              placeholder="DRONE_GITHUB_CLIENT_SECRET"
            />
          </Field>
          <Field
            label={t('workspaceSettings.delivery.droneGitlabClientIdEnv')}
            htmlFor="workspace-delivery-drone-gitlab-client-id-env"
          >
            <Input
              id="workspace-delivery-drone-gitlab-client-id-env"
              value={draft.deliveryDroneGitlabClientIdEnv}
              onChange={(event) => {
                updateDraft('deliveryDroneGitlabClientIdEnv', event.target.value);
              }}
              placeholder="DRONE_GITLAB_CLIENT_ID"
            />
          </Field>
          <Field
            label={t('workspaceSettings.delivery.droneGitlabClientSecretEnv')}
            htmlFor="workspace-delivery-drone-gitlab-client-secret-env"
          >
            <Input
              id="workspace-delivery-drone-gitlab-client-secret-env"
              value={draft.deliveryDroneGitlabClientSecretEnv}
              onChange={(event) => {
                updateDraft('deliveryDroneGitlabClientSecretEnv', event.target.value);
              }}
              placeholder="DRONE_GITLAB_CLIENT_SECRET"
            />
          </Field>
          <SwitchField
            label={t('workspaceSettings.delivery.droneGitAlwaysAuth')}
            checked={draft.deliveryDroneGitAlwaysAuth}
            onChange={(checked) => {
              updateDraft('deliveryDroneGitAlwaysAuth', checked);
            }}
          />
        </div>
      </div>

      <div className="grid gap-3 border-t border-border-light pt-4 dark:border-border-dark">
        <div className="text-xs font-semibold text-text-secondary dark:text-text-muted">
          {t('workspaceSettings.delivery.droneRunnerEnvironment')}
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <Field
            label={t('workspaceSettings.delivery.droneRunnerPort')}
            htmlFor="workspace-delivery-drone-runner-port"
          >
            <DraftNumberInput
              id="workspace-delivery-drone-runner-port"
              min={1}
              value={draft.deliveryDroneRunnerPort}
              fallback={3001}
              onCommit={(next) => {
                updateDraft('deliveryDroneRunnerPort', next);
              }}
            />
          </Field>
          <Field
            label={t('workspaceSettings.delivery.droneRunnerCapacity')}
            htmlFor="workspace-delivery-drone-runner-capacity"
          >
            <DraftNumberInput
              id="workspace-delivery-drone-runner-capacity"
              min={1}
              value={draft.deliveryDroneRunnerCapacity}
              fallback={2}
              onCommit={(next) => {
                updateDraft('deliveryDroneRunnerCapacity', next);
              }}
            />
          </Field>
          <Field
            label={t('workspaceSettings.delivery.droneRunnerName')}
            htmlFor="workspace-delivery-drone-runner-name"
          >
            <Input
              id="workspace-delivery-drone-runner-name"
              value={draft.deliveryDroneRunnerName}
              onChange={(event) => {
                updateDraft('deliveryDroneRunnerName', event.target.value);
              }}
              placeholder="memstack-drone-runner"
            />
          </Field>
          <Field
            label={t('workspaceSettings.delivery.droneRunnerRpcProto')}
            htmlFor="workspace-delivery-drone-runner-rpc-proto"
          >
            <Input
              id="workspace-delivery-drone-runner-rpc-proto"
              value={draft.deliveryDroneRunnerRpcProto}
              onChange={(event) => {
                updateDraft('deliveryDroneRunnerRpcProto', event.target.value);
              }}
              placeholder="http"
            />
          </Field>
          <Field
            label={t('workspaceSettings.delivery.droneRunnerRpcHost')}
            htmlFor="workspace-delivery-drone-runner-rpc-host"
          >
            <Input
              id="workspace-delivery-drone-runner-rpc-host"
              value={draft.deliveryDroneRunnerRpcHost}
              onChange={(event) => {
                updateDraft('deliveryDroneRunnerRpcHost', event.target.value);
              }}
              placeholder="drone-server"
            />
          </Field>
          <Field
            label={t('workspaceSettings.delivery.droneRunnerRpcSecretEnv')}
            htmlFor="workspace-delivery-drone-runner-rpc-secret-env"
          >
            <Input
              id="workspace-delivery-drone-runner-rpc-secret-env"
              value={draft.deliveryDroneRunnerRpcSecretEnv}
              onChange={(event) => {
                updateDraft('deliveryDroneRunnerRpcSecretEnv', event.target.value);
              }}
              placeholder="DRONE_RPC_SECRET"
            />
          </Field>
        </div>
      </div>
    </div>
  );
};
