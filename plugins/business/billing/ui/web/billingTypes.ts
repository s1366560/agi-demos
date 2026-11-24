export interface BillingTenant {
  id: string;
  name: string | null;
  plan: string;
  storage_limit: number;
  projects_limit?: number | null;
  users_limit?: number | null;
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
  membership_role?: 'admin' | 'owner';
  tenant: BillingTenant;
  usage: BillingUsage;
  invoices: Invoice[];
}

export interface UpgradePlanRequest {
  plan: 'free' | 'pro' | 'enterprise';
}

export interface UpgradePlanResponse {
  message: string;
  tenant: BillingTenant;
}

export interface BillingService {
  getBillingInfo(tenantId: string): Promise<BillingInfo>;
  upgradePlan(tenantId: string, plan: UpgradePlanRequest['plan']): Promise<UpgradePlanResponse>;
}
