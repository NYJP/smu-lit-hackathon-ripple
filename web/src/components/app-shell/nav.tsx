"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";
import { useSession } from "@/lib/session-context";

// Section 10.2: primary navigation, in this exact order. Admins additionally
// see People. Documents comes first deliberately — "the user's own material
// is the thing they own and return to."
const PRIMARY_LINKS = [
  { href: "/documents", label: "Documents" },
  { href: "/regulations", label: "Regulations" },
  { href: "/changes", label: "Changes" },
  { href: "/graph", label: "Graph" },
  { href: "/search", label: "Search" },
] as const;

export function PrimaryNav() {
  const pathname = usePathname();
  const { user } = useSession();

  const links = user?.role === "admin"
    ? [...PRIMARY_LINKS, { href: "/people", label: "People" } as const]
    : PRIMARY_LINKS;

  return (
    <nav className="flex items-center gap-1">
      {links.map((link) => {
        const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
        return (
          <Link
            key={link.href}
            href={link.href}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              active
                ? "bg-secondary text-secondary-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
