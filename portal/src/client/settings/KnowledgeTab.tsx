import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { type TabProps } from "./schemaFields";

/**
 * The prose the assistant may answer from. It goes into the cached system
 * prompt verbatim, so anything that promises an outcome does not belong here.
 *
 * One field, in the kit's form idiom: a label, the control, and the
 * description under it (`FormDescription` in
 * `src/features/settings/profile/profile-form.tsx`).
 */
export function KnowledgeTab({ config, onChange, disabled }: TabProps) {
  const words = String(config.knowledge ?? "").trim().split(/\s+/).filter(Boolean).length;

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor="config-knowledge">What the clinic is</Label>
      <Textarea
        id="config-knowledge"
        rows={24}
        aria-label="Knowledge"
        data-testid="config-knowledge"
        disabled={disabled}
        value={String(config.knowledge ?? "")}
        onChange={(event) =>
          onChange({ ...config, knowledge: event.target.value })
        }
      />
      <p className="text-muted-foreground text-sm">
        Facts about the clinic in plain prose. Keep it under 4,000 words; no
        promises, no medical claims. {words} words at the moment.
      </p>
    </div>
  );
}
