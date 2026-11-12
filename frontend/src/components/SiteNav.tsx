"use client";

import { FileTextIcon, HomeIcon, ListChecksIcon, TagsIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Home", icon: HomeIcon },
  { href: "/jobs", label: "Jobs", icon: ListChecksIcon },
  { href: "/skills", label: "Skills", icon: TagsIcon },
  { href: "/resume", label: "Resume", icon: FileTextIcon },
] as const;

/** The header's page links; the current page is highlighted. */
export function SiteNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="flex items-center gap-1">
      {LINKS.map(({ href, label, icon: Icon }) => {
        const current = href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            aria-current={current ? "page" : undefined}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm font-medium transition-colors sm:px-3",
              current ? "bg-secondary text-secondary-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-4" />
            {/* Phones show the current page's label and the others' icons (icons only on
                the narrowest); every label stays for screen readers. */}
            <span className={cn("max-[359px]:sr-only", !current && "max-[439px]:sr-only")}>{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
