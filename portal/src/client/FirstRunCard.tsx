import {
  IconCircle,
  IconCircleCheck,
  IconListCheck,
} from "@tabler/icons-react";
import { Link } from "react-router";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./components/ui/card";
import { type FirstRunStep } from "./firstRun";

/**
 * The "Getting set up" card above the overview's tiles: one line per step of
 * `firstRunSteps`, ticked when done, each linking to where it is done, and
 * nothing at all once the first tracked request exists. The steps are decided
 * on the server (`getFirstRunChecklist`); this only draws them.
 */
export function FirstRunCard({ steps }: { steps: FirstRunStep[] }) {
  const request = steps.find((step) => step.key === "request");
  if (!request || request.done) {
    return null;
  }
  const done = steps.filter((step) => step.done).length;

  return (
    <Card data-testid="first-run-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <IconListCheck className="size-5" />
          Getting set up
        </CardTitle>
        <CardDescription>
          What is left before the assistant takes real calls. This card goes
          away when the first request lands.{" "}
          <span data-testid="first-run-progress" className="text-foreground">
            {done} of {steps.length} done.
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {steps.map((step) => (
            <li
              key={step.key}
              data-testid={`first-run-step-${step.key}`}
              className="flex items-center gap-3 rounded-md border px-3 py-2 text-sm"
            >
              {step.done ? (
                <IconCircleCheck
                  data-testid={`first-run-done-${step.key}`}
                  className="text-primary size-5 shrink-0"
                />
              ) : (
                <IconCircle className="text-muted-foreground size-5 shrink-0" />
              )}
              <span
                className={
                  step.done ? "text-muted-foreground line-through" : undefined
                }
              >
                {step.label}
              </span>
              <Link
                to={step.to}
                className="text-muted-foreground ms-auto text-xs underline underline-offset-4"
              >
                {step.done ? "Open" : "Set up"}
              </Link>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
