import { useState } from "react";
import type {} from "../../../../../sdk/memstack-plugin-sdk/src/pageRuntime";
import { InvoiceTable, type InvoiceRow } from "./InvoiceTable";

interface Account {
  tenant: { name: string; plan: string; storage_limit: number };
  usage: { projects: number; users: number; memories: number; storage: number };
  invoices: InvoiceRow[];
}

export function TenantAccount({ plans, canChange, text, locale }: {
  plans: readonly string[];
  canChange: boolean;
  text: (english: string, chinese: string) => string;
  locale: string;
}) {
  const [account, setAccount] = useState<Account>();
  const [plan, setPlan] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function load(change: boolean) {
    setBusy(true);
    setError("");
    try {
      if (change) {
        const result = await window.memstack.invoke("change-plan", {plan}) as Pick<Account, "tenant">;
        setAccount(previous => previous && {...previous, tenant: result.tenant});
        setPlan("");
      }
      const fresh = await window.memstack.invoke("tenant-account") as Account;
      setAccount(fresh);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }
  return <section>
    <h2>{text("Tenant billing", "租户账单")}</h2>
    <button disabled={busy} onClick={() => void load(false)}>
      {account ? text("Refresh account", "刷新账户") : text("View tenant account", "查看租户账户")}
    </button>
    {account && <>
      <h3>{account.tenant.name}</h3>
      <dl>
        <dt>{text("Current plan", "当前套餐")}</dt><dd>{account.tenant.plan}</dd>
        <dt>{text("Storage used / limit (bytes)", "已用存储 / 上限（字节）")}</dt>
        <dd>{account.usage.storage.toLocaleString(locale)} / {account.tenant.storage_limit.toLocaleString(locale)}</dd>
        <dt>{text("Projects", "项目")}</dt><dd>{account.usage.projects}</dd>
        <dt>{text("Members", "成员")}</dt><dd>{account.usage.users}</dd>
        <dt>{text("Memories", "记忆")}</dt><dd>{account.usage.memories}</dd>
      </dl>
      {canChange && <div>
        <label>{text("New tenant plan", "租户新套餐")}
          <select value={plan} disabled={busy} onChange={event => setPlan(event.target.value)}>
            <option value="">{text("Select plan", "选择套餐")}</option>
            {plans.filter(id => id !== account.tenant.plan).map(id => <option key={id}>{id}</option>)}
          </select>
        </label>
        <button type="button" disabled={busy || !plan} onClick={() => void load(true)}>{text("Confirm plan change", "确认更改套餐")}</button>
      </div>}
      <h3>{text("Tenant invoice history", "租户历史发票")}</h3>
      {account.invoices.length ? <InvoiceTable invoices={account.invoices}/> : <p>{text("No invoices", "暂无发票")}</p>}
    </>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
