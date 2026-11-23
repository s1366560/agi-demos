import { useState } from "react";
import { createRoot } from "react-dom/client";
import type {} from "../../../../../sdk/memstack-plugin-sdk/src/pageRuntime";
import { CreateInvoice } from "./CreateInvoice";
import { InvoiceTable, type InvoiceRow } from "./InvoiceTable";

function AccountPage({
  commands,
  locale,
}: {
  commands: readonly string[];
  locale: string;
}) {
  const [quotes, setQuotes] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<readonly string[]>([]);
  const [invoices, setInvoices] = useState<InvoiceRow[] | null>(null);
  const [creating, setCreating] = useState(false);
  const busy = creating || pending.length > 0;
  const [error, setError] = useState("");
  const text = (en: string, zh: string) => (locale.startsWith("zh") ? zh : en);
  async function invoke(command: string) {
    const api = window.memstack;
    setPending((active) => [...active, command]);
    setError("");
    try {
      const result = await api.invoke(command);
      if (command === "list-invoices")
        setInvoices((result as { invoices: InvoiceRow[] }).invoices);
      else {
        const bytes = (
          result as { storage_limit: number }
        ).storage_limit.toLocaleString(locale);
        setQuotes((previous) => ({
          ...previous,
          [command]: bytes + text(" bytes", " 字节"),
        }));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setPending((active) => active.filter((id) => id !== command));
    }
  }
  return (
    <>
      <h1>{text("Plans and invoices", "套餐和发票")}</h1>
      {commands
        .filter((id) => id.startsWith("quote-"))
        .map((command) => (
          <p key={command}>
            <button disabled={busy} onClick={() => void invoke(command)}>
              {command.slice("quote-".length)}
            </button>{" "}
            <output aria-live="polite">{quotes[command]}</output>
          </p>
        ))}
      {commands.includes("list-invoices") && (
        <section>
          <button disabled={busy} onClick={() => void invoke("list-invoices")}>
            {text("Project invoices", "项目发票")}
          </button>
          {invoices &&
            (invoices.length ? (
              <InvoiceTable invoices={invoices} />
            ) : (
              <p role="status">{text("No invoices", "暂无发票")}</p>
            ))}
        </section>
      )}
      {commands.includes("create-invoice") && (
        <CreateInvoice
          disabled={pending.length > 0}
          onPending={setCreating}
          text={text}
          onCreated={(invoice) =>
            setInvoices((rows) => [
              invoice,
              ...(rows || []).filter((row) => row.id !== invoice.id),
            ])
          }
        />
      )}
      {error && <p role="alert">{error}</p>}
    </>
  );
}

void window.memstack.scope().then(({ commands, locale }) => {
  createRoot(document.getElementById("root")!).render(
    <AccountPage commands={commands} locale={locale} />,
  );
});
