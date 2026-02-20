/**
 * Billing Service
 * Handles billing, invoices, and subscription management
 */

import { httpClient } from './client/httpClient';

// Types
export interface BillingTenant {
  id: string;
  name: string | null;
  plan: string;
  storage_limit: number;
}

export interface BillingUsage {
  projects: number;
  memories: number;
  users: number;
  storage: number;
}

export interface Invoice {
  id: string;
  amount: number;
  currency: string;
  status: string;
  period_start: string;
  period_end: string;
  created_at: string;
  paid_at: string | null;
  invoice_url: string | null;
}

export interface BillingInfo {
  tenant: BillingTenant;
  usage: BillingUsage;
  invoices: Invoice[];
}

export interface InvoiceList {
  invoices: Invoice[];
}

export interface UpgradePlanRequest {
  plan: 'free' | 'pro' | 'enterprise';
}

export interface UpgradePlanResponse {
  message: string;
  tenant: BillingTenant;
}

const BASE_URL = '/tenants';

export const billingService = {
  /**
   * Get billing information for a tenant
   */
  async getBillingInfo(tenantId: string): Promise<BillingInfo> {
    const response = await httpClient.get<BillingInfo>(`${BASE_URL}/${tenantId}/billing`);
    return response;
  },

  /**
   * List all invoices for a tenant
   */
  async listInvoices(tenantId: string): Promise<InvoiceList> {
    const response = await httpClient.get<InvoiceList>(`${BASE_URL}/${tenantId}/invoices`);
    return response;
  },

  /**
   * Upgrade tenant plan
   */
  async upgradePlan(
    tenantId: string,
    plan: UpgradePlanRequest['plan']
  ): Promise<UpgradePlanResponse> {
    const response = await httpClient.post<UpgradePlanResponse>(`${BASE_URL}/${tenantId}/upgrade`, {
      plan,
    });
    return response;
  },
};
