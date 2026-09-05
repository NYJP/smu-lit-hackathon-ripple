"use client";

/**
 * Section 10.3 /people: admin only, the roster, real data from GET /users.
 *
 * The wave brief scopes this page to the roster itself ("Real data from
 * GET /users"), narrower than the full PRD route description (add/rename/
 * delete-with-reassign). The backing endpoints already exist and are
 * fully implemented (api/routers/users.py, not a 501 stub) — this page
 * intentionally does not expose them yet; see the report for why.
 */

import { useEffect, useState } from "react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useSession } from "@/lib/session-context";

function formatLastSeen(value: string | null): string {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function PeoplePage() {
  const { user, roster, loading, refreshRoster } = useSession();
  // Starts true so the mount-time refresh below never calls setState
  // synchronously from within the effect body — only from its (already
  // async) .finally() callback.
  const [refreshing, setRefreshing] = useState(true);

  useEffect(() => {
    let cancelled = false;
    refreshRoster().finally(() => {
      if (!cancelled) setRefreshing(false);
    });
    // Only on mount: the roster is not scoped by identity, so switching
    // accounts elsewhere does not need to trigger this again.
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) {
    return null;
  }

  if (user?.role !== "admin") {
    return (
      <div className="mx-auto max-w-2xl py-16 text-sm text-muted-foreground">
        This page is only available to admin accounts.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl py-10">
      <h1 className="text-xl font-medium">People</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Everyone sees the roster; only admins can change it — you cannot tag
        someone you cannot name.
      </p>

      <div className="mt-6 overflow-x-auto rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Role</TableHead>
              <TableHead className="text-right">Documents</TableHead>
              <TableHead>Last seen</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {roster.map((person) => (
              <TableRow key={person.id}>
                <TableCell className="font-medium">
                  {person.display_name}
                  {person.id === user.id && (
                    <span className="ml-2 text-xs text-muted-foreground">(you)</span>
                  )}
                </TableCell>
                <TableCell className="capitalize text-muted-foreground">
                  {person.role}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {person.document_count}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatLastSeen(person.last_seen_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {refreshing && (
        <p className="mt-2 text-xs text-muted-foreground">Refreshing…</p>
      )}
    </div>
  );
}
