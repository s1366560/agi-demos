export interface InvoiceRow {
  id: string;
  currency: string;
  amount: number;
  status: string;
}

export function InvoiceTable({
  invoices,
}: {
  invoices: readonly InvoiceRow[];
}) {
  return (
    <table>
      <tbody>
        {invoices.map((invoice) => (
          <tr key={invoice.id}>
            <td>
              <code>{invoice.id}</code>
            </td>
            <td>
              {invoice.currency} {invoice.amount}
            </td>
            <td>{invoice.status}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
