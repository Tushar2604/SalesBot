"use client";

/**
 * Session provider: holds the signed-in user, their workspaces, and the
 * currently selected workspace. Restores the session from the refresh cookie on
 * mount so a page reload does not bounce the user to /login.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type Me, type Workspace, type WorkspaceRole } from "@/lib/api";

const WORKSPACE_KEY = "salesrobo.workspace";

type SessionState = {
  status: "loading" | "authenticated" | "anonymous";
  me: Me | null;
  workspace: Workspace | null;
  role: WorkspaceRole | null;
  selectWorkspace: (id: string) => void;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
};

const SessionContext = createContext<SessionState | null>(null);

function readStoredWorkspace(): string | null {
  try {
    return window.localStorage.getItem(WORKSPACE_KEY);
  } catch {
    // Private mode / blocked storage: fall back to the first workspace.
    return null;
  }
}

function storeWorkspace(id: string): void {
  try {
    window.localStorage.setItem(WORKSPACE_KEY, id);
  } catch {
    /* non-fatal */
  }
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [status, setStatus] = useState<SessionState["status"]>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const result = await api.restoreSession();
    if (!result) {
      setMe(null);
      setStatus("anonymous");
      return;
    }
    setMe(result);
    setStatus("authenticated");

    const stored = readStoredWorkspace();
    const valid = result.workspaces.some((w) => w.workspace.id === stored);
    setWorkspaceId(valid ? stored : (result.workspaces[0]?.workspace.id ?? null));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selectWorkspace = useCallback((id: string) => {
    setWorkspaceId(id);
    storeWorkspace(id);
  }, []);

  const signOut = useCallback(async () => {
    await api.logout().catch(() => undefined);
    setMe(null);
    setWorkspaceId(null);
    setStatus("anonymous");
    router.push("/login");
  }, [router]);

  const value = useMemo<SessionState>(() => {
    const membership = me?.workspaces.find((w) => w.workspace.id === workspaceId) ?? null;
    return {
      status,
      me,
      workspace: membership?.workspace ?? null,
      role: membership?.role ?? null,
      selectWorkspace,
      refresh: load,
      signOut,
    };
  }, [me, workspaceId, status, selectWorkspace, load, signOut]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used inside <SessionProvider>");
  return context;
}

/** True when the signed-in user's role meets a minimum. */
export function hasRole(role: WorkspaceRole | null, minimum: WorkspaceRole): boolean {
  const rank: Record<WorkspaceRole, number> = { member: 0, admin: 1, owner: 2 };
  return role !== null && rank[role] >= rank[minimum];
}
