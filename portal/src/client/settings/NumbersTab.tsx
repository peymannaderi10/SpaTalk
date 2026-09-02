import { type Draft } from "./schemaFields";

/**
 * Read only, and deliberately so: `runtime.tenant_numbers` is authoritative and
 * a number arrives there when the agency buys it, not when someone types it
 * into a form.
 */
export function NumbersTab({
  config,
  numbers,
}: {
  config: Draft;
  numbers: { number: string; kind: string }[];
}) {
  return (
    <div data-testid="numbers-tab" className="space-y-6 text-sm">
      <p className="text-muted-foreground">
        Numbers are mapped to this tenant by the agency. Ask us to add, move or
        release one.
      </p>

      <table className="w-full text-left">
        <thead className="text-muted-foreground">
          <tr>
            <th className="py-2 font-normal">Number</th>
            <th className="py-2 font-normal">Used for</th>
          </tr>
        </thead>
        <tbody>
          {numbers.length === 0 ? (
            <tr>
              <td className="text-muted-foreground py-2" colSpan={2}>
                No number is mapped to this tenant yet.
              </td>
            </tr>
          ) : (
            numbers.map((number) => (
              <tr key={number.number} className="border-border border-t">
                <td className="py-2">{number.number}</td>
                <td className="py-2">
                  {number.kind === "voice" ? "Calls" : "Texts"}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Fact label="Texts are sent from" value={config.sms_from_number} />
        <Fact label="Live transfer goes to" value={config.transfer_number} />
        <Fact label="The clinic's own number" value={config.public_phone} />
        <Fact label="Default booking link" value={config.booking_url_default} />
      </dl>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="border-border rounded-lg border p-3">
      <dt className="text-muted-foreground text-xs uppercase">{label}</dt>
      <dd className="text-foreground mt-1">{String(value ?? "—") || "—"}</dd>
    </div>
  );
}
