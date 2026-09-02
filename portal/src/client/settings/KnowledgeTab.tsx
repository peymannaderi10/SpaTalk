import { Textarea } from "../components/ui/textarea";
import { type TabProps } from "./schemaFields";

/**
 * The prose the assistant may answer from. It goes into the cached system
 * prompt verbatim, so anything that promises an outcome does not belong here.
 */
export function KnowledgeTab({ config, onChange, disabled }: TabProps) {
  const words = String(config.knowledge ?? "").trim().split(/\s+/).filter(Boolean).length;

  return (
    <div className="space-y-2">
      <p className="text-muted-foreground text-sm">
        Facts about the clinic in plain prose. Keep it under 4,000 words; no
        promises, no medical claims. {words} words at the moment.
      </p>
      <Textarea
        rows={24}
        aria-label="Knowledge"
        data-testid="config-knowledge"
        disabled={disabled}
        value={String(config.knowledge ?? "")}
        onChange={(event) =>
          onChange({ ...config, knowledge: event.target.value })
        }
      />
    </div>
  );
}
