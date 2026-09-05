import { IconDotsVertical } from "@tabler/icons-react";
import { cn } from "../utils";
import { Button } from "./ui/button";

/**
 * The three dots at the top right of a page. Pressed, the page switches to
 * internal view — the agency's own figures, which a client looking over the
 * admin's shoulder is not meant to see; pressed again, it turns back. It is
 * meant to be passed over by anyone who does not know what it is for.
 */
export function InternalToggle({
  internal,
  onToggle,
}: {
  internal: boolean;
  onToggle: () => void;
}) {
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      className={cn(
        "text-muted-foreground",
        internal && "bg-accent text-accent-foreground",
      )}
      aria-label={internal ? "Back to the client's view" : "Internal view"}
      aria-pressed={internal}
      data-testid="pricing-assumptions"
      onClick={onToggle}
    >
      <IconDotsVertical className="size-4" />
    </Button>
  );
}
