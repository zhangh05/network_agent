import type { Workspace } from "../types";

export function pickInitialWorkspaceId(workspaces: Workspace[]): string | null {
  if (workspaces.length === 0) return null;
  const explicitDefault = workspaces.find((w) => w.is_default);
  if (explicitDefault) return explicitDefault.workspace_id;
  const namedDefault = workspaces.find((w) => w.workspace_id === "default");
  if (namedDefault) return namedDefault.workspace_id;
  return workspaces[0].workspace_id;
}

export function shouldReplacePersistedWorkspace(
  currentWorkspaceId: string | null,
  workspaces: Workspace[],
): boolean {
  if (!currentWorkspaceId) return true;
  const exists = workspaces.some((w) => w.workspace_id === currentWorkspaceId);
  if (!exists) return true;
  return currentWorkspaceId !== "default" && isTestWorkspaceId(currentWorkspaceId);
}

function isTestWorkspaceId(workspaceId: string): boolean {
  return /(^|_)(test|e2e)(_|$)/.test(workspaceId) ||
    workspaceId.startsWith("api_contract") ||
    workspaceId.startsWith("closure_") ||
    workspaceId.startsWith("ws_");
}
