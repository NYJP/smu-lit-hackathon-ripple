"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, ChevronDown, FileStack, Menu, Network, Scale, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

const groups = [
  { label: "Documents", href: "/documents", icon: FileStack },
  { label: "Regulatory", icon: Scale, children: [{ label: "Regulations", href: "/regulations", description: "Source instruments and amendments" }, { label: "Requirements", href: "/requirements", description: "Extracted regulatory obligations" }] },
  { label: "Review", icon: BookOpen, children: [{ label: "Changes", href: "/changes", description: "Detected regulatory changes" }, { label: "Impacts", href: "/impacts", description: "Review and remediation queue" }] },
  { label: "Graph", href: "/graph", icon: Network },
  { label: "Simulations", href: "/simulations", icon: Sparkles },
] as const;

const secondary = [{ label: "Search", href: "/search" }, { label: "Scans", href: "/scans" }];
const active = (pathname: string, href: string) => pathname === href || pathname.startsWith(`${href}/`);

function GroupMenu({ group, pathname }: { group: Extract<(typeof groups)[number], { children: unknown }>; pathname: string }) {
  const selected = group.children.some(item => active(pathname, item.href));
  return <DropdownMenu>
    <DropdownMenuTrigger asChild><Button variant={selected ? "secondary" : "ghost"} size="sm" className="gap-1 px-2.5">{group.label}<ChevronDown className="size-3.5" /></Button></DropdownMenuTrigger>
    <DropdownMenuContent align="center" className="w-64 p-1.5">
      {group.children.map(item => <DropdownMenuItem key={item.href} asChild className="p-2"><Link href={item.href} className="block"><span className="font-medium">{item.label}</span><span className="mt-0.5 block text-xs text-muted-foreground">{item.description}</span></Link></DropdownMenuItem>)}
    </DropdownMenuContent>
  </DropdownMenu>;
}

export function PrimaryNav() {
  const pathname = usePathname();
  return <>
    <nav aria-label="Primary navigation" className="hidden items-center justify-center gap-0.5 lg:flex">
      {groups.map(group => "children" in group
        ? <GroupMenu key={group.label} group={group} pathname={pathname} />
        : <Button key={group.href} asChild variant={active(pathname, group.href) ? "secondary" : "ghost"} size="sm" className="px-2.5"><Link href={group.href}>{group.label}</Link></Button>)}
    </nav>
    <div className="justify-self-end lg:hidden">
      <Sheet><SheetTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="Open navigation"><Menu /></Button></SheetTrigger>
        <SheetContent side="left" className="w-[19rem]">
          <SheetHeader><SheetTitle>Ripple</SheetTitle><SheetDescription>Navigate your regulatory workspace.</SheetDescription></SheetHeader>
          <nav aria-label="Mobile navigation" className="space-y-5 overflow-y-auto px-4 pb-6">
            {groups.map(group => <div key={group.label}>
              {"children" in group ? <><p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">{group.label}</p><div className="space-y-1">{group.children.map(item => <Button key={item.href} asChild variant={active(pathname,item.href)?"secondary":"ghost"} className="w-full justify-start"><Link href={item.href}>{item.label}</Link></Button>)}</div></>
                : <Button asChild variant={active(pathname,group.href)?"secondary":"ghost"} className="w-full justify-start"><Link href={group.href}><group.icon />{group.label}</Link></Button>}
            </div>)}
            <div className="border-t pt-4">{secondary.map(item => <Button key={item.href} asChild variant={active(pathname,item.href)?"secondary":"ghost"} className="w-full justify-start"><Link href={item.href}>{item.label}</Link></Button>)}</div>
          </nav>
        </SheetContent>
      </Sheet>
    </div>
  </>;
}
