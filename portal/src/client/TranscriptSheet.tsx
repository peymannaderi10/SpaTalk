import { IconAlertTriangle, IconBan } from "@tabler/icons-react";
import { useState } from "react";
import { type readConversation } from "wasp/client/operations";
import { CallNotes } from "./CallNotes";
import { Button } from "./components/ui/button";
import { ScrollArea } from "./components/ui/scroll-area";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "./components/ui/sheet";
import { bandLabel, channelLabel, formatDateTime } from "./formatting";
import { cn } from "./utils";

/** What the runtime answers when someone reads a transcript. */
export type TranscriptDetail = Awaited<ReturnType<typeof readConversation>>;

/**
 * What was said, in the kit's chat layout (`src/features/chats/index.tsx` in
 * `satnaing/shadcn-admin`) inside a sheet: a header naming who the
 * conversation was with and on which channel, the notes the runtime drafted
 * above the messages, and the messages as bubbles — the assistant and the team
 * on one side, the caller on the other.
 *
 * One component for both pages that open one, so a transcript read from the
 * conversations list and a transcript read from a request card cannot drift
 * apart. The conversations list is the only one that offers to block a number,
 * because that is the only place the whole number is in front of a person.
 */
export function TranscriptSheet({
  detail,
  label,
  testId,
  busy = false,
  onClose,
  onBlock,
}: {
  detail: TranscriptDetail | null;
  /** The tenant's own wording for the notes block. */
  label: string;
  testId: string;
  busy?: boolean;
  onClose: () => void;
  /** Offered only where blocking the caller makes sense. */
  onBlock?: () => Promise<void>;
}) {
  const [blocked, setBlocked] = useState(false);
  const [blockProblem, setBlockProblem] = useState<string | null>(null);

  if (!detail) {
    return null;
  }

  const { conversation, messages, items } = detail;
  const who =
    conversation.caller ?? conversation.external_ref ?? "no caller id";

  return (
    <Sheet
      open
      onOpenChange={(next) => {
        if (!next) {
          setBlocked(false);
          setBlockProblem(null);
          onClose();
        }
      }}
    >
      <SheetContent
        side="right"
        data-testid={testId}
        className="flex w-full flex-col gap-0 overflow-hidden p-0 sm:max-w-xl"
      >
        <SheetHeader className="bg-card flex-none gap-3 border-b p-4 pe-12">
          <div>
            <SheetTitle className="text-base">{who}</SheetTitle>
            <SheetDescription>
              {channelLabel(conversation.channel)} ·{" "}
              {bandLabel(conversation.band)} ·{" "}
              {formatDateTime(conversation.started_at)}
            </SheetDescription>
          </div>

          {onBlock && (
            <div className="text-sm">
              {blocked ? (
                <p data-testid="blocked-note" className="text-muted-foreground">
                  Blocked. Its texts are kept here and never answered. Undo it
                  under Settings, Numbers.
                </p>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  className="w-fit"
                  data-testid="block-number"
                  disabled={busy}
                  onClick={async () => {
                    setBlockProblem(null);
                    try {
                      await onBlock();
                      setBlocked(true);
                    } catch (caught) {
                      setBlockProblem(
                        (caught as { message?: string }).message ??
                          "That number could not be blocked.",
                      );
                    }
                  }}
                >
                  <IconBan className="size-4" />
                  Block this number
                </Button>
              )}
              {blockProblem && (
                <p className="text-destructive mt-2">{blockProblem}</p>
              )}
            </div>
          )}
        </SheetHeader>

        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-4 p-4">
            {conversation.health_context && (
              <p className="border-border text-muted-foreground flex items-start gap-2 rounded-md border p-3 text-sm">
                <IconAlertTriangle className="mt-0.5 size-4 shrink-0" />
                The caller volunteered health information. It is in the
                transcript and nowhere else.
              </p>
            )}

            <CallNotes
              notes={conversation.notes}
              label={label}
              testId="conversation-notes"
            />

            <ol className="chat-flex flex flex-col gap-4">
              {messages.map((message, index) => {
                const ours =
                  message.role === "assistant" || message.role === "staff";
                return (
                  <li
                    key={index}
                    className={cn(
                      "chat-box flex max-w-72 flex-col px-3 py-2 text-sm shadow-sm wrap-break-word",
                      ours
                        ? "bg-primary/90 text-primary-foreground self-end rounded-[16px_16px_0_16px]"
                        : "bg-muted self-start rounded-[16px_16px_16px_0]",
                    )}
                  >
                    {message.text}
                    <span
                      className={cn(
                        "mt-1 block text-xs font-light italic",
                        ours
                          ? "text-primary-foreground/85 text-end"
                          : "text-muted-foreground",
                      )}
                    >
                      {message.role}
                    </span>
                  </li>
                );
              })}
            </ol>

            {items.length > 0 && (
              <section className="border-border mt-2 rounded-md border p-3">
                <h3 className="text-sm font-medium">
                  Requests from this conversation
                </h3>
                <ul className="text-muted-foreground mt-2 space-y-1 text-sm">
                  {items.map((item) => (
                    <li key={item.id}>
                      #{item.id} · {item.type} · {item.state}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
