import Link from "next/link";
import { Search } from "lucide-react";

import { PrimaryNav } from "./nav";
import { AccountMenu } from "./account-menu";
import { Button } from "@/components/ui/button";

// Section 10.2: "A Scan control and the account menu sit in the header on
// every page." Scanning itself is not built yet (build order step 8), so
// the control is an honest link to /scans rather than a button that fires
// an unbuilt action.
export function AppHeader() {
  return (
    <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/85">
      <div className="mx-auto grid h-14 max-w-[96rem] grid-cols-[auto_1fr_auto] items-center gap-2 px-3 sm:gap-4 sm:px-6 lg:grid-cols-[1fr_auto_1fr]">
        <Link href="/dashboard" className="w-fit text-sm font-semibold tracking-tight">
          Ripple
        </Link>
        <PrimaryNav />
      <div className="flex shrink-0 items-center justify-self-end gap-1.5 sm:gap-2">
        <Button asChild variant="ghost" size="icon-sm" className="hidden sm:inline-flex">
          <Link href="/search" aria-label="Search"><Search /></Link>
        </Button>
        <Button asChild variant="outline" size="sm">
          <Link href="/scans">Scan</Link>
        </Button>
        <AccountMenu />
      </div>
      </div>
    </header>
  );
}
