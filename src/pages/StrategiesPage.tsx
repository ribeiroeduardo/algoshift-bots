import { ChevronDown, ChevronRight, Pencil, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { DashboardLayout } from "@/components/dashboard/DashboardLayout";
import { Drawer } from "@/components/ui/Drawer";
import { Modal } from "@/components/ui/Modal";
import { getSupabaseClient, isSupabaseEnabled } from "@/lib/supabaseClient";
import { cn } from "@/lib/utils";
import type { StrategyVersionRow, StrategyVersionStatus } from "@/types/database";

type StrategyWithVersions = {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  strategy_versions: StrategyVersionRow[];
};

const emptyVersions: StrategyVersionRow[] = [];

const statusLabel: Record<StrategyVersionStatus, string> = {
  draft: "Draft",
  active: "Active",
  archived: "Archived",
};

const statusBadge = (s: StrategyVersionStatus) => {
  const base =
    "inline-flex items-center rounded-full px-1.5 py-0.5 text-[11px] font-medium";
  if (s === "active") {
    return cn(base, "bg-emerald-500/12 text-emerald-300");
  }
  if (s === "archived") {
    return cn(base, "bg-white/[0.08] text-[#666]");
  }
  return cn(base, "bg-amber-500/12 text-amber-200/90");
};

const sortVersions = (rows: StrategyVersionRow[]) =>
  [...rows].sort((a, b) => b.version_number - a.version_number);

/** DB requires version_number > 0; empty number input often becomes 0 or NaN → 400 from PostgREST */
const toPositiveVersion = (n: number, fallback: number) => {
  const x = Math.trunc(Number(n));
  if (!Number.isFinite(x) || x < 1) {
    return Math.max(1, Math.trunc(fallback) || 1);
  }
  return x;
};

const StrategiesPage = () => {
  const supa = isSupabaseEnabled();
  const [rows, setRows] = useState<StrategyWithVersions[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [openStrategyIds, setOpenStrategyIds] = useState<Set<string>>(() => new Set());

  const [addModalOpen, setAddModalOpen] = useState(false);
  const [addName, setAddName] = useState("");

  const [strategyDrawer, setStrategyDrawer] = useState<{ id: string; name: string } | null>(null);
  const [strategyName, setStrategyName] = useState("");

  const [versionDrawer, setVersionDrawer] = useState<
    | { mode: "create"; strategyId: string; nextNumber: number }
    | {
        mode: "edit";
        strategyId: string;
        id: string;
        versionNumber: number;
        content: string;
        status: StrategyVersionStatus;
      }
    | null
  >(null);
  const versionCodeRef = useRef<HTMLTextAreaElement | null>(null);
  const [vForm, setVForm] = useState({
    versionNumber: 1,
    status: "draft" as StrategyVersionStatus,
  });

  const refetch = useCallback(async () => {
    if (!supa) {
      return;
    }
    const s = getSupabaseClient()!;
    setLoading(true);
    setLoadError(null);
    const { data, error } = await s
      .from("strategies")
      .select(
        "id, name, created_at, updated_at, strategy_versions ( id, strategy_id, version_number, content, status, created_at, updated_at )",
      )
      .order("updated_at", { ascending: false });
    setLoading(false);
    if (error) {
      setLoadError(error.message);
      return;
    }
    const list = (data ?? []) as unknown as StrategyWithVersions[];
    setRows(
      list.map((r) => ({
        ...r,
        strategy_versions: sortVersions(
          (r as { strategy_versions?: StrategyVersionRow[] | null }).strategy_versions ??
            emptyVersions,
        ),
      })),
    );
  }, [supa]);

  useEffect(() => {
    if (!supa) {
      setRows([]);
      return;
    }
    void refetch();
  }, [supa, refetch]);

  useEffect(() => {
    if (strategyDrawer) {
      setStrategyName(strategyDrawer.name);
    }
  }, [strategyDrawer]);

  useEffect(() => {
    if (addModalOpen) {
      setAddName("");
    }
  }, [addModalOpen]);

  useEffect(() => {
    if (!versionDrawer) {
      return;
    }
    if (versionDrawer.mode === "create") {
      setVForm({ versionNumber: versionDrawer.nextNumber, status: "draft" });
    } else {
      setVForm({
        versionNumber: versionDrawer.versionNumber,
        status: versionDrawer.status,
      });
    }
  }, [versionDrawer]);

  const canUseDb = supa;

  const toggleOpen = (id: string) => {
    setOpenStrategyIds((prev) => {
      const n = new Set(prev);
      if (n.has(id)) {
        n.delete(id);
      } else {
        n.add(id);
      }
      return n;
    });
  };

  const onAddStrategy = async () => {
    if (!canUseDb) {
      return;
    }
    const name = addName.trim();
    if (!name) {
      return;
    }
    setLoadError(null);
    const s = getSupabaseClient()!;
    const { error } = await s.from("strategies").insert({ name });
    if (error) {
      setLoadError(error.message);
      return;
    }
    setAddModalOpen(false);
    void refetch();
  };

  const onSaveStrategy = async () => {
    if (!canUseDb || !strategyDrawer) {
      return;
    }
    const name = strategyName.trim();
    if (!name) {
      return;
    }
    const s = getSupabaseClient()!;
    const { error } = await s.from("strategies").update({ name }).eq("id", strategyDrawer.id);
    if (error) {
      setLoadError(error.message);
      return;
    }
    setStrategyDrawer(null);
    void refetch();
  };

  const onDeleteStrategy = async (id: string) => {
    if (!canUseDb) {
      return;
    }
    if (!window.confirm("Delete this strategy and all its versions?")) {
      return;
    }
    const s = getSupabaseClient()!;
    const { error } = await s.from("strategies").delete().eq("id", id);
    if (error) {
      setLoadError(error.message);
      return;
    }
    void refetch();
  };

  const onSaveVersion = async () => {
    if (!canUseDb || !versionDrawer) {
      return;
    }
    setLoadError(null);
    const s = getSupabaseClient()!;
    const code = versionCodeRef.current?.value ?? "";
    const fallbackN =
      versionDrawer.mode === "create" ? versionDrawer.nextNumber : versionDrawer.versionNumber;
    const versionNumber = toPositiveVersion(vForm.versionNumber, fallbackN);
    const payload = {
      version_number: versionNumber,
      content: code,
      status: vForm.status,
    };
    if (versionDrawer.mode === "create") {
      const { error } = await s.from("strategy_versions").insert({
        strategy_id: versionDrawer.strategyId,
        ...payload,
      });
      if (error) {
        setLoadError(
          [error.message, (error as { details?: string }).details].filter(Boolean).join(" — "),
        );
        return;
      }
    } else {
      const { error } = await s
        .from("strategy_versions")
        .update(payload)
        .eq("id", versionDrawer.id);
      if (error) {
        setLoadError(
          [error.message, (error as { details?: string }).details].filter(Boolean).join(" — "),
        );
        return;
      }
    }
    setVersionDrawer(null);
    void refetch();
  };

  const onDeleteVersion = async (versionId: string) => {
    if (!canUseDb) {
      return;
    }
    if (!window.confirm("Delete this version?")) {
      return;
    }
    const s = getSupabaseClient()!;
    const { error } = await s.from("strategy_versions").delete().eq("id", versionId);
    if (error) {
      setLoadError(error.message);
      return;
    }
    void refetch();
  };

  const openNewVersion = (st: StrategyWithVersions) => {
    const maxN =
      st.strategy_versions.length > 0
        ? Math.max(...st.strategy_versions.map((v) => v.version_number))
        : 0;
    setVersionDrawer({ mode: "create", strategyId: st.id, nextNumber: maxN + 1 || 1 });
  };

  const openVersionForEdit = async (strategyId: string, versionId: string) => {
    if (!canUseDb) {
      return;
    }
    setLoadError(null);
    const s = getSupabaseClient()!;
    const { data, error } = await s
      .from("strategy_versions")
      .select("id, strategy_id, version_number, content, status")
      .eq("id", versionId)
      .single();
    if (error || !data) {
      setLoadError(error?.message ?? "Could not load version");
      return;
    }
    setVersionDrawer({
      mode: "edit",
      strategyId,
      id: data.id,
      versionNumber: data.version_number,
      content: data.content,
      status: data.status,
    });
  };

  return (
    <DashboardLayout title="Strategies">
      {!supa && (
        <p className="text-[13px] text-[#919191]">
          Set <span className="font-mono text-[12px]">VITE_SUPABASE_URL</span> and{" "}
          <span className="font-mono text-[12px]">VITE_SUPABASE_ANON_KEY</span> in{" "}
          <span className="font-mono text-[12px]">.env</span> to save strategies.
        </p>
      )}
      {canUseDb && loadError && <p className="mb-3 text-rose-400/90">Error: {loadError}</p>}
      {canUseDb && (
        <>
          <div className="mb-4 flex items-center justify-between">
            <span className="font-mono text-[11px] font-medium uppercase tracking-wide text-[#666]">
              All strategies
            </span>
            <button
              type="button"
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-[#ededed] px-3 text-[13px] font-medium text-[#0a0a0a] hover:bg-white"
              onClick={() => setAddModalOpen(true)}
            >
              <Plus className="h-4 w-4" />
              Add Strategy
            </button>
          </div>

          {loading && rows.length === 0 && (
            <p className="text-[#666]">Loading strategies…</p>
          )}

          {!loading && rows.length === 0 && (
            <p className="text-[#666]">No strategies yet. Use “Add Strategy” to create one.</p>
          )}

          {rows.length > 0 && (
            <ul className="flex flex-col gap-3">
              {rows.map((st) => {
                const isOpen = openStrategyIds.has(st.id);
                return (
                  <li
                    key={st.id}
                    className="overflow-hidden rounded-lg bg-[#1a1a1a] ring-1 ring-inset ring-white/[0.06]"
                  >
                    <div className="flex items-center gap-2 px-3.5 py-3">
                      <button
                        type="button"
                        className="inline-flex h-7 w-7 items-center justify-center text-[#919191] hover:text-white"
                        onClick={() => toggleOpen(st.id)}
                        aria-expanded={isOpen}
                      >
                        {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </button>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[13px] font-semibold leading-tight text-[#ededed]">
                          {st.name}
                        </div>
                        <div className="mt-0.5 font-mono text-[11px] text-[#666]">
                          {st.strategy_versions.length} version{st.strategy_versions.length === 1 ? "" : "s"}
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-0.5">
                        <button
                          type="button"
                          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-[#919191] hover:bg-white/[0.05] hover:text-[#ededed]"
                          title="Edit"
                          onClick={() => setStrategyDrawer({ id: st.id, name: st.name })}
                        >
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-[#919191] hover:bg-white/[0.05] hover:text-rose-400"
                          title="Delete"
                          onClick={() => void onDeleteStrategy(st.id)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                    {isOpen ? (
                      <div className="border-t border-white/[0.04]">
                        <div className="flex items-center justify-between border-b border-white/[0.04] px-3.5 py-2">
                          <span className="font-mono text-[11px] text-[#666]">VERSIONS</span>
                          <button
                            type="button"
                            className="inline-flex h-7 items-center gap-1 rounded-md bg-white/[0.06] px-2 text-[12px] text-[#ededed] hover:bg-white/[0.1]"
                            onClick={() => openNewVersion(st)}
                          >
                            <Plus className="h-3.5 w-3.5" />
                            Add version
                          </button>
                        </div>
                        {st.strategy_versions.length === 0 ? (
                          <p className="px-3.5 py-3 text-[13px] text-[#666]">No versions yet.</p>
                        ) : (
                          <ul className="divide-y divide-white/[0.04]">
                            {st.strategy_versions.map((v) => (
                              <li
                                key={v.id}
                                className="flex items-start gap-3 px-3.5 py-2.5 text-[13px]"
                              >
                                <div className="w-8 shrink-0 text-center font-mono text-[12px] text-[#dedede]">
                                  {v.version_number}
                                </div>
                                <div className="min-w-0 flex-1">
                                  <div className="mb-0.5 flex flex-wrap items-center gap-2">
                                    <span className={statusBadge(v.status)}>{statusLabel[v.status]}</span>
                                    <span className="font-mono text-[11px] text-[#666]">
                                      {v.content.length.toLocaleString()} chars ·{" "}
                                      {v.content.length === 0
                                        ? 0
                                        : (v.content.match(/\n/g)?.length ?? 0) + 1}{" "}
                                      lines
                                    </span>
                                  </div>
                                  <p className="text-[11px] text-[#666]">Edit to view or change full code.</p>
                                </div>
                                <div className="flex shrink-0 gap-0.5">
                                  <button
                                    type="button"
                                    className="inline-flex h-8 w-8 items-center justify-center rounded-md text-[#919191] hover:bg-white/[0.05] hover:text-[#ededed]"
                                    title="Edit version"
                                    onClick={() => void openVersionForEdit(st.id, v.id)}
                                  >
                                    <Pencil className="h-3.5 w-3.5" />
                                  </button>
                                  <button
                                    type="button"
                                    className="inline-flex h-8 w-8 items-center justify-center rounded-md text-[#919191] hover:bg-white/[0.05] hover:text-rose-400"
                                    title="Delete version"
                                    onClick={() => void onDeleteVersion(v.id)}
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </button>
                                </div>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}

      <Modal
        open={addModalOpen}
        onOpenChange={setAddModalOpen}
        title="Add Strategy"
        footer={
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="h-8 rounded-md px-3 text-[13px] text-[#919191] hover:bg-white/[0.05] hover:text-[#ededed]"
              onClick={() => setAddModalOpen(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="h-8 rounded-md bg-[#ededed] px-3 text-[13px] font-medium text-[#0a0a0a] hover:bg-white"
              onClick={() => void onAddStrategy()}
              disabled={!addName.trim()}
            >
              Save
            </button>
          </div>
        }
      >
        <label className="mb-1 block text-[12px] text-[#666]">Name</label>
        <input
          className="w-full rounded-md border-0 bg-[#111] px-3 py-2 text-[13px] text-[#ededed] ring-1 ring-inset ring-white/[0.1] focus:outline-none focus:ring-2 focus:ring-[hsl(212,100%,48%)]"
          value={addName}
          onChange={(e) => setAddName(e.target.value)}
          placeholder="e.g. Mean reversion scalp"
          autoFocus
        />
      </Modal>

      <Drawer
        open={strategyDrawer !== null}
        onOpenChange={(o) => {
          if (!o) {
            setStrategyDrawer(null);
          }
        }}
        title="Edit strategy"
        footer={
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="h-8 rounded-md px-3 text-[13px] text-[#919191] hover:bg-white/[0.05] hover:text-[#ededed]"
              onClick={() => setStrategyDrawer(null)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="h-8 rounded-md bg-[#ededed] px-3 text-[13px] font-medium text-[#0a0a0a] hover:bg-white"
              onClick={() => void onSaveStrategy()}
              disabled={!strategyName.trim()}
            >
              Save
            </button>
          </div>
        }
      >
        <label className="mb-1 block text-[12px] text-[#666]">Name</label>
        <input
          className="w-full rounded-md border-0 bg-[#111] px-3 py-2 text-[13px] text-[#ededed] ring-1 ring-inset ring-white/[0.1] focus:outline-none focus:ring-2 focus:ring-[hsl(212,100%,48%)]"
          value={strategyName}
          onChange={(e) => setStrategyName(e.target.value)}
          placeholder="My strategy"
          autoFocus
        />
      </Drawer>

      <Drawer
        open={versionDrawer !== null}
        onOpenChange={(o) => {
          if (!o) {
            setVersionDrawer(null);
          }
        }}
        widthClassName="w-full max-w-5xl"
        title={versionDrawer?.mode === "create" ? "New version" : "Edit version"}
        footer={
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="h-8 rounded-md px-3 text-[13px] text-[#919191] hover:bg-white/[0.05] hover:text-[#ededed]"
              onClick={() => setVersionDrawer(null)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="h-8 rounded-md bg-[#ededed] px-3 text-[13px] font-medium text-[#0a0a0a] hover:bg-white"
              onClick={() => void onSaveVersion()}
            >
              Save
            </button>
          </div>
        }
      >
        <div className="mb-3 grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-[12px] text-[#666]">Version #</label>
            <input
              type="number"
              min={1}
              step={1}
              className="w-full rounded-md border-0 bg-[#111] px-3 py-2 text-[13px] text-[#ededed] ring-1 ring-inset ring-white/[0.1] focus:outline-none focus:ring-2 focus:ring-[hsl(212,100%,48%)]"
              value={vForm.versionNumber < 1 ? 1 : vForm.versionNumber}
              onChange={(e) => {
                const raw = e.target.value;
                const n = raw === "" ? 1 : Number.parseInt(raw, 10);
                setVForm((f) => ({
                  ...f,
                  versionNumber: Number.isFinite(n) && n > 0 ? n : 1,
                }));
              }}
            />
          </div>
          <div>
            <label className="mb-1 block text-[12px] text-[#666]">Status</label>
            <select
              className="h-[38px] w-full rounded-md border-0 bg-[#111] px-2 text-[13px] text-[#ededed] ring-1 ring-inset ring-white/[0.1] focus:outline-none focus:ring-2 focus:ring-[hsl(212,100%,48%)]"
              value={vForm.status}
              onChange={(e) =>
                setVForm((f) => ({ ...f, status: e.target.value as StrategyVersionStatus }))
              }
            >
              <option value="draft">Draft</option>
              <option value="active">Active</option>
              <option value="archived">Archived</option>
            </select>
          </div>
        </div>
        <p className="mb-1 text-[11px] text-[#666]">
          Full file saved on Save. Large scripts (e.g. 10k+ lines) use the editor scroll; nothing is
          truncated at save.
        </p>
        <label className="mb-1 block text-[12px] text-[#666]">Content (python)</label>
        <textarea
          key={
            versionDrawer
              ? versionDrawer.mode === "create"
                ? `c-${versionDrawer.strategyId}-${versionDrawer.nextNumber}`
                : `e-${versionDrawer.id}`
              : "closed"
          }
          ref={versionCodeRef}
          defaultValue={versionDrawer?.mode === "edit" ? versionDrawer.content : ""}
          className={cn(
            "h-[min(80vh,1200px)] w-full min-h-[20rem] resize-y overflow-auto",
            "rounded-md border-0 bg-[#0a0a0a] px-3 py-2",
            "font-mono text-[12px] leading-[1.4] text-[#e4e4e4]",
            "whitespace-pre ring-1 ring-inset ring-white/[0.1] focus:outline-none focus:ring-2",
            "focus:ring-[hsl(212,100%,48%)]",
          )}
          placeholder="# your bot logic (paste full script)"
          spellCheck={false}
          autoComplete="off"
        />
      </Drawer>
    </DashboardLayout>
  );
};

export default StrategiesPage;
