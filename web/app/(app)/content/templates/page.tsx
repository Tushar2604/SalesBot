"use client";

/** Saved post copy: create, edit, duplicate, delete, or open in the composer. */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, linkedinApi, type LinkedInAccount } from "@/lib/api";
import { contentApi, relativeTime, type Template } from "@/lib/content-api";
import { useSession } from "@/lib/session";
import {
  CardSkeleton,
  ConfirmDialog,
  EmptyState,
  Modal,
  useToast,
} from "@/components/content/ContentUi";
import { IconCopy, IconPencil, IconPlus, IconTrash } from "@/components/app/icons";

export default function TemplatesPage() {
  const { workspace } = useSession();
  const workspaceId = workspace?.id ?? null;
  const router = useRouter();
  const toast = useToast();

  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [accounts, setAccounts] = useState<LinkedInAccount[]>([]);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Template | "new" | null>(null);
  const [removing, setRemoving] = useState<Template | null>(null);
  const [busy, setBusy] = useState(false);

  const [name, setName] = useState("");
  const [content, setContent] = useState("");

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      setTemplates(await contentApi.templates(workspaceId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load templates.");
      setTemplates([]);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!workspaceId) return;
    linkedinApi.accounts(workspaceId).then(setAccounts).catch(() => setAccounts([]));
  }, [workspaceId]);

  const openEditor = (template: Template | "new") => {
    setEditing(template);
    setName(template === "new" ? "" : template.name);
    setContent(template === "new" ? "" : template.content);
  };

  const save = async () => {
    if (!workspaceId || !editing) return;
    setBusy(true);
    try {
      if (editing === "new") {
        await contentApi.createTemplate(workspaceId, { name: name.trim(), content });
        toast.success("Template created.");
      } else {
        await contentApi.updateTemplate(workspaceId, editing.id, { name: name.trim(), content });
        toast.success("Template updated.");
      }
      setEditing(null);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not save the template.");
    } finally {
      setBusy(false);
    }
  };

  /**
   * "Use template" creates a real draft rather than passing text through the
   * URL — the composer then owns it, and autosave has something to write to.
   */
  const startFromTemplate = async (template: Template) => {
    if (!workspaceId) return;
    const account = accounts[0];
    if (!account) {
      toast.error("Connect a LinkedIn account before creating a post.");
      return;
    }
    setBusy(true);
    try {
      const post = await contentApi.createPost(workspaceId, {
        linkedin_account_id: account.id,
        content: template.content,
        media: template.media.map((asset) => ({ media_asset_id: asset.id })),
      });
      router.push(`/content/${post.id}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not start a post.");
      setBusy(false);
    }
  };

  const duplicate = async (template: Template) => {
    if (!workspaceId) return;
    try {
      await contentApi.createTemplate(workspaceId, {
        name: `${template.name} (copy)`,
        content: template.content,
        media_asset_ids: template.media.map((asset) => asset.id),
      });
      toast.success("Template duplicated.");
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not duplicate the template.");
    }
  };

  if (!workspaceId) {
    return <EmptyState title="No workspace selected" body="Pick a workspace to see its templates." />;
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-[13.5px] text-slate-500">
          Reusable copy for posts you write often.
        </p>
        <button type="button" onClick={() => openEditor("new")} className="btn-primary !py-1.5 text-[13px]">
          <IconPlus className="h-4 w-4" />
          New template
        </button>
      </div>

      {error && <p className="mb-3 text-[13px] text-state-bad">{error}</p>}

      {templates === null ? (
        <CardSkeleton count={2} />
      ) : templates.length === 0 ? (
        <EmptyState
          title="No templates yet"
          body="Save a post you write often as a template, then start from it next time instead of a blank editor."
          action={
            <button type="button" onClick={() => openEditor("new")} className="btn-primary">
              Create template
            </button>
          }
        />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {templates.map((template) => (
            <li key={template.id} className="card flex flex-col">
              <h3 className="font-display text-[15px] font-bold text-ink-950">{template.name}</h3>
              <p className="mt-1 text-[12px] text-slate-400">
                Updated {relativeTime(template.updated_at)}
              </p>
              <p className="mt-2 line-clamp-5 flex-1 whitespace-pre-wrap text-[13px] leading-relaxed text-slate-600">
                {template.content || <span className="italic text-slate-400">Empty</span>}
              </p>
              <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void startFromTemplate(template)}
                  className="btn-primary !py-1.5 text-[12.5px]"
                >
                  Use template
                </button>
                <button
                  type="button"
                  onClick={() => openEditor(template)}
                  className="btn-ghost !py-1.5 text-[12.5px]"
                >
                  <IconPencil className="h-3.5 w-3.5" />
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => void duplicate(template)}
                  className="btn-ghost !py-1.5 text-[12.5px]"
                >
                  <IconCopy className="h-3.5 w-3.5" />
                  Duplicate
                </button>
                <button
                  type="button"
                  onClick={() => setRemoving(template)}
                  className="btn-ghost !ml-auto !py-1.5 text-[12.5px] text-state-bad"
                >
                  <IconTrash className="h-3.5 w-3.5" />
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {editing && (
        <Modal
          title={editing === "new" ? "New template" : "Edit template"}
          onClose={() => setEditing(null)}
          wide
          footer={
            <>
              <button type="button" onClick={() => setEditing(null)} className="btn-ghost">
                Cancel
              </button>
              <button
                type="button"
                disabled={busy || !name.trim()}
                onClick={() => void save()}
                className="btn-primary"
              >
                {busy ? "Saving…" : "Save"}
              </button>
            </>
          }
        >
          <label className="block">
            <span className="label">Name</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Launch announcement"
              className="input"
            />
          </label>
          <label className="mt-3 block">
            <span className="label">Content</span>
            <textarea
              value={content}
              onChange={(event) => setContent(event.target.value)}
              rows={10}
              placeholder="The copy you want to start from…"
              className="input resize-y leading-relaxed"
            />
          </label>
          <p className="mt-1 text-[12px] text-slate-500">{content.length} characters</p>
        </Modal>
      )}

      {removing && (
        <ConfirmDialog
          title="Delete this template?"
          body={`"${removing.name}" will be removed. Posts already written from it are not affected.`}
          confirmLabel="Delete"
          destructive
          busy={busy}
          onClose={() => setRemoving(null)}
          onConfirm={async () => {
            setBusy(true);
            try {
              await contentApi.deleteTemplate(workspaceId, removing.id);
              toast.success("Template deleted.");
              setRemoving(null);
              await load();
            } catch (err) {
              toast.error(err instanceof ApiError ? err.message : "Could not delete the template.");
            } finally {
              setBusy(false);
            }
          }}
        />
      )}
    </div>
  );
}
