/**
 * A choice (say, how a list is sorted) that this browser remembers between
 * visits, in localStorage. Server rendering and the first render in the
 * browser use the fallback, so the page hydrates cleanly; the remembered
 * choice follows right after. Without localStorage (some private modes) the
 * choice still works, for as long as the page is open.
 */

import { useCallback, useSyncExternalStore } from "react";

const listeners = new Set<() => void>();
const memory = new Map<string, string>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener); // another tab changed it
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key) ?? memory.get(key) ?? null;
  } catch {
    return memory.get(key) ?? null;
  }
}

export function useStoredChoice<T extends string>(key: string, choices: readonly T[], fallback: T): [T, (next: T) => void] {
  const stored = useSyncExternalStore(
    subscribe,
    () => read(key),
    () => null,
  );
  const value = stored !== null && (choices as readonly string[]).includes(stored) ? (stored as T) : fallback;
  const choose = useCallback(
    (next: T) => {
      memory.set(key, next);
      try {
        window.localStorage.setItem(key, next);
      } catch {
        // Not allowed: remembered in memory only.
      }
      listeners.forEach((listener) => listener());
    },
    [key],
  );
  return [value, choose];
}

/** Forget every remembered choice (tests). */
export function resetStoredChoices(): void {
  memory.clear();
}
