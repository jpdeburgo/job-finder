import { ExternalLinkIcon } from "lucide-react";
import type { AnchorHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

type Props = AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string;
  children: ReactNode;
  /** Hide the external-link icon (e.g. when the parent renders its own). */
  plain?: boolean;
};

/** A link that always opens in a new tab without leaking `window.opener`. */
export function ExternalLink({ href, children, plain = false, className, ...rest }: Props) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cn("inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline", className)}
      {...rest}
    >
      {children}
      {!plain && <ExternalLinkIcon aria-hidden="true" className="size-3.5 shrink-0 opacity-70" />}
    </a>
  );
}
