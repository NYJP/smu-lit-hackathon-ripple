import Link from "next/link";

import { PrimaryNav } from "./nav";
import { AccountMenu } from "./account-menu";
import { Button } from "@/components/ui/button";

// Section 10.2: "A Scan control and the account menu sit in the header on
// every page." Scanning itself is not built yet (build order step 8), so
// the control is an honest link to /scans rather than a button that fires
// an unbuilt action.
export function AppHeader() {
  return (
    <header className="flex h-14 items-center justify-between border-b px-6">
      <div className="flex items-center gap-6">
        <Link href="/dashboard" className="text-sm font-semibold tracking-tight">
          Ripple
        </Link>
        <PrimaryNav />
      </div>
      <div className="flex items-center gap-3">
        <Button asChild variant="outline" size="sm">
          <Link href="/scans">Scan</Link>
        </Button>
        <AccountMenu />
      </div>
    </header>
  );
}
