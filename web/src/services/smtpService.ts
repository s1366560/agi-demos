import { hostControlClient } from './client/hostControlClient';

export interface SmtpConfigResponse {
  id: string;
  tenant_id: string;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password_masked: string;
  from_email: string;
  from_name: string | null;
  use_tls: boolean;
}

export interface SmtpConfigCreate {
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password: string;
  from_email: string;
  from_name?: string | null;
  use_tls: boolean;
}

export interface SmtpTestRequest {
  recipient_email: string;
}

export const smtpService = {
  getConfig: (tenantId: string) =>
    hostControlClient.get<SmtpConfigResponse | null>(`/tenants/${tenantId}/smtp-config`),

  upsertConfig: (tenantId: string, data: SmtpConfigCreate) =>
    hostControlClient.put<SmtpConfigResponse>(`/tenants/${tenantId}/smtp-config`, data),

  deleteConfig: (tenantId: string) => hostControlClient.delete(`/tenants/${tenantId}/smtp-config`),

  testSmtp: (tenantId: string, data: SmtpTestRequest) =>
    hostControlClient.post(`/tenants/${tenantId}/smtp-config/test`, data),
};
