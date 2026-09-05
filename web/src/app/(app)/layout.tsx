"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { AppHeader } from "@/components/app-shell/header";
import { AppFooter } from "@/components/app-shell/footer";
import { useSession } from "@/lib/session-context";

/**
 * The app shell (section 10.2). Proxy (src/proxy.ts) already redirects an
 * unauthenticated request here before it renders, using cookie presence
 * alone (optimistic). This layout is the second, authoritative check: once
 * SessionProvider's GET /auth/me round trip resolves, a still-null user
 * (expired or unknown session, cookie present but invalid) is redirected
 * client-side — no full reload, per the same rule that governs switching.
 */
export default function AppShellLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/who");
    }
  }, [loading, user, router]);

  if (loading || !user) {
    return null;
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <AppHeader />
      <main className="flex-1">{children}</main>
      <AppFooter />
    </div>
  );
}
