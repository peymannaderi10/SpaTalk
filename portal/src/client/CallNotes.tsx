/**
 * The notes the runtime drafted from a transcript, shown where the follow-up
 * happens: on the request card and above the messages in a transcript.
 *
 * Three rules the runtime relies on this component to keep (call notes plan,
 * Task N1). Nothing is shown when there are no notes — a conversation can have
 * been drafted and have had nothing worth passing on, and a heading with
 * nothing under it would read as a loss. The label always sits above the
 * sentences, so a reader sees that they were drafted before they read them.
 * And the notes are prose from a model, rendered as text and never as markup.
 */
export function CallNotes({
  notes,
  label,
  testId,
}: {
  notes: string | null | undefined;
  label: string;
  testId: string;
}) {
  if (!notes) {
    return null;
  }
  return (
    <section className="mt-3">
      <h3 className="text-muted-foreground text-xs uppercase">{label}</h3>
      <p
        data-testid={testId}
        className="text-foreground mt-1 text-sm whitespace-pre-line"
      >
        {notes}
      </p>
    </section>
  );
}
