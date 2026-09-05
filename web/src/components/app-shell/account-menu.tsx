"use client";

/**
 * Section 5.5 / 10.2: current name and role, the other accounts for
 * one-click switching, and the "not secured" line. Switching calls
 * chooseAccount() and nothing else — no navigation, no reload
 * (acceptance criterion 42): the context update alone re-renders every
 * consumer (this menu, the nav's People link, any page reading useSession).
 */

import { useState } from "react";
import { ChevronDown } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSession } from "@/lib/session-context";

export function AccountMenu() {
  const { user, roster, chooseAccount } = useSession();
  const [switching, setSwitching] = useState<string | null>(null);

  if (!user) return null;

  const others = roster.filter((r) => r.id !== user.id);

  async function handleSwitch(userId: string) {
    setSwitching(userId);
    try {
      await chooseAccount(userId);
    } finally {
      setSwitching(null);
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-secondary">
          <span className="flex flex-col items-end leading-tight">
            <span className="font-medium">{user.display_name}</span>
            <span className="text-xs text-muted-foreground">{user.role}</span>
          </span>
          <ChevronDown className="size-4 text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="font-normal">
          <div className="font-medium">{user.display_name}</div>
          <div className="text-xs text-muted-foreground">{user.role}</div>
        </DropdownMenuLabel>
        {others.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
              Switch to
            </DropdownMenuLabel>
            {others.map((account) => (
              <DropdownMenuItem
                key={account.id}
                disabled={switching !== null}
                onSelect={(e) => {
                  e.preventDefault();
                  handleSwitch(account.id);
                }}
              >
                <div className="flex w-full items-center justify-between">
                  <span>{account.display_name}</span>
                  <span className="text-xs text-muted-foreground">{account.role}</span>
                </div>
              </DropdownMenuItem>
            ))}
          </>
        )}
        <DropdownMenuSeparator />
        <p className="px-2 py-2 text-xs leading-snug text-muted-foreground">
          Accounts are not secured. Anyone using this install can view as anyone.
        </p>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
