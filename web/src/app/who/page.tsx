"use client";

/**
 * Section 10.3: the account picker. Three names on a plain centred card,
 * each with role and document count, one click to continue. No password
 * field, no sign-up.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";

import { useSession } from "@/lib/session-context";

export default function WhoPage() {
  const { roster, loading, chooseAccount } = useSession();
  const [selecting, setSelecting] = useState<string | null>(null);
  const router = useRouter();

  async function handleChoose(userId: string) {
    setSelecting(userId);
    try {
      await chooseAccount(userId);
      router.push("/dashboard");
    } finally {
      setSelecting(null);
    }
  }

  return (
    <div className="flex min-h-full flex-1 items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm rounded-lg border p-8 text-center">
        <h1 className="text-lg font-semibold">Ripple</h1>
        <p className="mt-1 text-sm text-muted-foreground">Choose an account to continue.</p>

        <div className="mt-6 flex flex-col gap-2">
          {loading && (
            <p className="py-6 text-sm text-muted-foreground">Loading accounts…</p>
          )}
          {!loading && roster.length === 0 && (
            <p className="py-6 text-sm text-muted-foreground">
              Could not reach the Ripple API.
            </p>
          )}
          {roster.map((account) => (
            <button
              key={account.id}
              type="button"
              disabled={selecting !== null}
              onClick={() => handleChoose(account.id)}
              className="flex items-center justify-between rounded-md border px-4 py-3 text-left transition-colors hover:bg-secondary disabled:opacity-50"
            >
              <span>
                <span className="block text-sm font-medium">{account.display_name}</span>
                <span className="block text-xs text-muted-foreground">
                  {account.role} · {account.document_count} document
                  {account.document_count === 1 ? "" : "s"}
                </span>
              </span>
              <span className="text-sm font-medium text-muted-foreground">
                {selecting === account.id ? "…" : "Continue"}
              </span>
            </button>
          ))}
        </div>

        <p className="mt-6 text-xs leading-snug text-muted-foreground">
          Accounts are not secured. Anyone using this install can view as
          anyone.
        </p>
      </div>
    </div>
  );
}
