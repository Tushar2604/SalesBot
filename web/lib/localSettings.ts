"use client";

/**
 * Local-only persistence for settings that have no backend model yet
 * (Safe Mode extras, AI Personalization, blocklist CSV staging, credits,
 * API keys, etc.). Scoped per workspace so switching workspaces doesn't leak
 * state between them. This is a deliberate stand-in for endpoints that would
 * otherwise need new tables — swap for a real API call when one exists.
 */

import { useCallback, useEffect, useState } from "react";

function storageKey(workspaceId: string, key: string): string {
  return `salesrobo.${workspaceId}.${key}`;
}

export function readLocal<T>(workspaceId: string, key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(storageKey(workspaceId, key));
    if (!raw) return fallback;
    const parsed: unknown = JSON.parse(raw);
    // Arrays and primitives must come back as themselves: spreading them into an
    // object turns ["a"] into {"0":"a"} and a string into its characters.
    if (Array.isArray(fallback)) return (Array.isArray(parsed) ? parsed : fallback) as T;
    if (fallback !== null && typeof fallback === "object") {
      return parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)
        ? ({ ...fallback, ...parsed } as T)
        : fallback;
    }
    return (parsed ?? fallback) as T;
  } catch {
    return fallback;
  }
}

export function writeLocal<T>(workspaceId: string, key: string, value: T): void {
  try {
    window.localStorage.setItem(storageKey(workspaceId, key), JSON.stringify(value));
  } catch {
    /* private mode / quota — non-fatal, state just won't persist */
  }
}

/** Same shape as `useState`, but persisted to localStorage under this workspace. */
export function useLocalState<T>(workspaceId: string | null, key: string, initial: T) {
  const [value, setValue] = useState<T>(initial);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!workspaceId) return;
    setValue(readLocal(workspaceId, key, initial));
    setLoaded(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, key]);

  const update = useCallback(
    (next: T | ((prev: T) => T)) => {
      setValue((prev) => {
        const resolved = typeof next === "function" ? (next as (p: T) => T)(prev) : next;
        if (workspaceId) writeLocal(workspaceId, key, resolved);
        return resolved;
      });
    },
    [workspaceId, key],
  );

  return [value, update, loaded] as const;
}
