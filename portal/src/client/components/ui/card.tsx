import { cva, type VariantProps } from "class-variance-authority"
import * as React from "react"

import { cn } from "../../utils"

/*
 * The registry card, plus the two surface variants the portal had added to it
 * before the kit was vendored. `accent` and `subtle` (named `bento` before the
 * refresh) paint the card in the tokens of the same name. The third variant
 * the portal carried, `faded`, is gone: it painted `text-card-faded-foreground`,
 * a token no stylesheet ever defined, and no page ever asked for it.
 */
const cardVariants = cva(
  "flex flex-col gap-6 rounded-xl border py-6 shadow-sm",
  {
    variants: {
      variant: {
        default: "bg-card text-card-foreground",
        accent:
          "bg-card-accent text-card-accent-foreground transition-transform duration-300 hover:scale-[1.02]",
        subtle:
          "border-none bg-card-subtle text-card-subtle-foreground shadow-none transition-transform duration-300 hover:scale-[1.02]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Card({
  className,
  variant,
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof cardVariants>) {
  return (
    <div
      data-slot="card"
      className={cn(cardVariants({ variant }), className)}
      {...props}
    />
  )
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={cn(
        "@container/card-header grid auto-rows-min grid-rows-[auto_auto] items-start gap-2 px-6 has-data-[slot=card-action]:grid-cols-[1fr_auto] [.border-b]:pb-6",
        className
      )}
      {...props}
    />
  )
}

function CardTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-title"
      className={cn("leading-none font-semibold", className)}
      {...props}
    />
  )
}

function CardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  )
}

function CardAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-action"
      className={cn(
        "col-start-2 row-span-2 row-start-1 self-start justify-self-end",
        className
      )}
      {...props}
    />
  )
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-content"
      className={cn("px-6", className)}
      {...props}
    />
  )
}

function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-footer"
      className={cn("flex items-center px-6 [.border-t]:pt-6", className)}
      {...props}
    />
  )
}

export {
  Card,
  cardVariants,
  CardHeader,
  CardFooter,
  CardTitle,
  CardAction,
  CardDescription,
  CardContent,
}
