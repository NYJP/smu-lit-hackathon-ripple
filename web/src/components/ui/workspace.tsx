import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { ArrowRight, Inbox } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "cn";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export function PageFrame({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mx-auto w-full max-w-6xl space-y-6 px-4 py-7 sm:px-6 sm:py-9", className)} {...props} />;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  className,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("motion-safe:animate-in motion-safe:fade-in motion-safe:duration-300", className)}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          {eyebrow ? <div className="mb-1 text-sm font-medium text-muted-foreground">{eyebrow}</div> : null}
          <h1 className="text-2xl font-semibold tracking-[-0.025em] sm:text-3xl">{title}</h1>
          {description ? <p className="mt-1.5 max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  );
}

export function SectionHeader({
  title,
  description,
  action,
  id,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  id?: string;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 id={id} className="text-base font-semibold tracking-tight">{title}</h2>
        {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function Surface({
  className,
  elevated = false,
  tone = "default",
  ...props
}: HTMLAttributes<HTMLDivElement> & { elevated?: boolean; tone?: "plain" | "subtle" | "default" }) {
  return (
    <Card
      className={cn(
        "gap-0 py-0 transition-colors duration-200",
        tone === "plain" && "border-transparent bg-transparent shadow-none",
        tone === "subtle" && "border-transparent bg-muted/35 shadow-none",
        elevated && "shadow-sm",
        className,
      )}
      {...props}
    />
  );
}

export function MetricCard({
  label,
  value,
  href,
  icon: Icon,
  supporting,
  compact = false,
  emphasized = false,
}: {
  label: string;
  value: number;
  href: string;
  icon: LucideIcon;
  supporting?: ReactNode;
  compact?: boolean;
  emphasized?: boolean;
}) {
  return (
    <Link href={href} className="group block rounded-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
      <Surface tone={emphasized ? "default" : "subtle"} className={cn("h-full transition-transform duration-200 motion-safe:hover:-translate-y-0.5", compact ? "p-3.5" : "p-4", emphasized && "border-foreground/15 shadow-sm")}>
        <div className="flex items-start justify-between gap-3">
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
          <Icon aria-hidden className="size-4 text-muted-foreground" />
        </div>
        <p className={cn("font-semibold tabular-nums tracking-tight", compact ? "mt-2 text-2xl" : "mt-3 text-3xl")}>{value}</p>
        <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>{supporting}</span>
          <ArrowRight aria-hidden className="size-3.5 transition-transform duration-200 group-hover:translate-x-0.5" />
        </div>
      </Surface>
    </Link>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon: Icon = Inbox,
  className,
}: {
  title: string;
  description: ReactNode;
  action?: ReactNode;
  icon?: LucideIcon;
  className?: string;
}) {
  return (
    <div className={cn("flex min-h-44 flex-col items-center justify-center px-5 py-10 text-center", className)}>
      <span className="mb-3 rounded-full bg-muted p-2.5"><Icon aria-hidden className="size-5 text-muted-foreground" /></span>
      <h3 className="font-medium">{title}</h3>
      <p className="mt-1 max-w-md text-sm leading-6 text-muted-foreground">{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function LoadingSkeleton({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div aria-label="Loading" aria-busy="true" className={cn("space-y-3 p-4", className)}>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="h-16 animate-pulse rounded-lg bg-muted motion-reduce:animate-none" />
      ))}
    </div>
  );
}

export function InlineAction({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  return (
    <Button asChild variant="ghost" size="sm" className={cn("-mr-2", className)}>
      <Link href={href}>{children}<ArrowRight aria-hidden className="size-3.5" /></Link>
    </Button>
  );
}
