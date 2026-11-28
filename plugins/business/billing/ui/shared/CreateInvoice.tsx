import { useRef, useState } from "react";
import type {} from "../../../../../sdk/memstack-plugin-sdk/src/pageRuntime";
import type { InvoiceRow } from "./InvoiceTable";

export function CreateInvoice({
  text,
  onCreated,
  disabled,
  onPending,
}: {
  text: (en: string, zh: string) => string;
  disabled: boolean;
  onPending: (pending: boolean) => void;
  onCreated: (invoice: InvoiceRow) => void;
}) {
  const form = useRef<HTMLFormElement>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  async function create() {
    if (disabled || pending || !form.current?.reportValidity()) return;
    const data = new FormData(form.current);
    setPending(true);
    onPending(true);
    setMessage("");
    try {
      const result = (await window.memstack.invoke("create-invoice", {
        idempotency_key: data.get("reference"),
        amount: Number(data.get("amount")),
        currency: data.get("currency"),
        period_start: data.get("start") + "T00:00:00Z",
        period_end: data.get("end") + "T00:00:00Z",
      })) as { error?: string; invoice?: InvoiceRow };
      if (!result.invoice)
        throw new Error(result.error || "invoice_unavailable");
      onCreated(result.invoice);
      setMessage(text("Invoice saved", "发票已保存"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setPending(false);
      onPending(false);
    }
  }
  return (
    <form
      ref={form}
      onKeyDown={(event) => {
        if (event.key === "Enter" && event.target instanceof HTMLInputElement) {
          event.preventDefault();
          void create();
        }
      }}
    >
      <fieldset disabled={pending || disabled}>
        <legend>{text("Create invoice", "创建发票")}</legend>
        <label>
          {text("Invoice reference", "发票业务编号")}
          <input name="reference" required maxLength={128} />
        </label>
        <label>
          {text("Amount in minor units", "金额（最小货币单位）")}
          <input
            name="amount"
            type="number"
            min="0"
            max="2147483647"
            step="1"
            required
          />
        </label>
        <label>
          {text("Currency", "币种")}
          <input
            name="currency"
            required
            pattern="[A-Z]{3}"
            maxLength={3}
            defaultValue="USD"
          />
        </label>
        <label>
          {text("Period start (UTC)", "账期开始（UTC）")}
          <input name="start" type="date" required />
        </label>
        <label>
          {text("Period end (UTC)", "账期结束（UTC）")}
          <input name="end" type="date" required />
        </label>
        <button type="button" onClick={() => void create()}>
          {text("Save invoice", "保存发票")}
        </button>
      </fieldset>
      <p role="status">{message}</p>
    </form>
  );
}
