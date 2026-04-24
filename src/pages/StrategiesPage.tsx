import { ChevronDown, ChevronRight, Pencil, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { DashboardLayout } from "@/components/dashboard/DashboardLayout";
import { Drawer } from "@/components/ui/Drawer";
import { Modal } from "@/components/ui/Modal";
import { updateBotRuntimeStatus } from "@/lib/botStatusUpdate";
import { getSupabaseClient, isSupabaseEnabled } from "@/lib/supabaseClient";
import { cn } from "@/lib/utils";
import type { BotRow, BotStatus } from "@/types/database";

type StrategyWithBots = {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  bots: BotRow[];
};

const emptyBots: BotRow[] = [];

/** Bybit-style (BTCUSDT, BTCUSDT.P) or legacy CCXT BASE/QUOTE */
const TRADING_PAIR_RE =
  /^[A-Z0-9]{5,}$|^[A-Z0-9]{3,}\.P$|^[A-Z0-9]+\/[A-Z0-9]+(:[A-Z0-9]+)?$/;

const runtimeLabel: Record<BotStatus, string> = {
  stopped: "Stopped",
  running: "Running",
  paused: "Paused",
  error: "Error",
};

const runtimeBadge = (s: BotStatus) => {
  const base =
    "inline-flex items-center rounded-full px-1.5 py-0.5 text-[11px] font-medium";
  if (s === "running") {
    return cn(base, "bg-sky-500/15 text-sky-200");
  }
  if (s === "error") {
    return cn(base, "bg-rose-500/15 text-rose-200");
  }
  if (s === "paused") {
    return cn(base, "bg-white/[0.08] text-[#aaa]");
  }
  return cn(base, "bg-white/[0.06] text-[#888]");
};

const sortBots = (rows: BotRow[]) => [...rows].sort((a, b) => b.version_number - a.version_number);

/** DB requires version_number > 0 */
const toPositiveVersion = (n: number, fallback: number) => {
  const x = Math.trunc(Number(n));
  if (!Number.isFinite(x) || x < 1) {
    return Math.max(1, Math.trunc(fallback) || 1);
  }
  return x;
};

const normalizePair = (raw: string) => raw.trim().toUpperCase();

type PgishError = {
  message: string;
  code?: string;
  details?: string;
  hint?: string;
};

const formatPostgrestError = (e: PgishError) => {
  const parts = [e.message];
  if (e.hint) {
    parts.push(`hint: ${e.hint}`);
  }
  if (e.details) {
    parts.push(`details: ${e.details}`);
  }
  if (e.code) {
    parts.push(`code: ${e.code}`);
  }
  return parts.join(" | ");
};

/** DevTools → Console: full Supabase/PostgREST errors when save fails */
const logBotSave = (
  step: "start" | "insert_ok" | "update_ok" | "insert_fail" | "update_fail" | "exception",
  ctx: Record<string, unknown>,
) => {
  const tag = "[algoshift Strategies/bot save]";
  if (step === "start") {
    console.info(tag, step, ctx);
    return;
  }
  if (step.endsWith("_ok")) {
    console.info(tag, step, ctx);
    return;
  }
  console.error(tag, step, ctx);
};

const StrategiesPage = () => {
  const supa = isSupabaseEnabled();
  const [rows, setRows] = useState<StrategyWithBots[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [botSaveError, setBotSaveError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [openStrategyIds, setOpenStrategyIds] = useState<Set<string>>(() => new Set());

  const [addModalOpen, setAddModalOpen] = useState(false);
  const [addName, setAddName] = useState("");

  const [strategyDrawer, setStrategyDrawer] = useState<{ id: string; name: string } | null>(null);
  const [strategyName, setStrategyName] = useState("");

  const [botDrawer, setBotDrawer] = useState<
    | { mode: "create"; strategyId: string; nextVersion: number }
    | {
        mode: "edit";
        strategyId: string;
        bot: BotRow;
      }
    | null
  >(null);
  const botCodeRef = useRef<HTMLTextAreaElement | null>(null);
  const [bForm, setBForm] = useState({
    name: "",
    versionNumber: 1,
    tradingPair: "BTCUSDT.P",
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
        `id, name, created_at, updated_at,
         bots ( id, name, strategy_id, content, version_number, trading_pair, exchange, market_type, status, params, last_error, created_at, updated_at )`,
      )
      .order("updated_at", { ascending: false });
    setLoading(false);
    if (error) {
      setLoadError(error.message);
      return;
    }
    const list = (data ?? []) as unknown as StrategyWithBots[];
    setRows(
      list.map((r) => ({
        ...r,
        bots: sortBots((r as { bots?: BotRow[] | null }).bots ?? emptyBots),
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
    if (!botDrawer) {
      return;
    }
    if (botDrawer.mode === "create") {
      setBForm({
        name: "",
        versionNumber: botDrawer.nextVersion,
        tradingPair: "BTCUSDT.P",
      });
    } else {
      const b = botDrawer.bot;
      setBForm({
        name: b.name,
        versionNumber: b.version_number,
        tradingPair: b.trading_pair,
      });
    }
  }, [botDrawer]);

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

  const onDeleteStrategy = async (id: string, botCount: number) => {
    if (!canUseDb) {
      return;
    }
    if (botCount > 0) {
      setLoadError(`Delete ${botCount} bot(s) under this strategy first.`);
      return;
    }
    if (!window.confirm("Delete this strategy?")) {
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

  const onSaveBot = async () => {
    if (!canUseDb || !botDrawer) {
      return;
    }
    setLoadError(null);
    setBotSaveError(null);
    const s = getSupabaseClient()!;
    const code = botCodeRef.current?.value ?? "";
    const pair = normalizePair(bForm.tradingPair);
    if (!TRADING_PAIR_RE.test(pair)) {
      const msg =
        "Ticker must be Bybit-style: BTCUSDT or BTCUSDT.P (or legacy BASE/QUOTE). Uppercase letters/digits.";
      setLoadError(msg);
      setBotSaveError(msg);
      console.warn(
        "[algoshift Strategies/bot save] validation:pair",
        { pair, pattern: "BTCUSDT / BTCUSDT.P" },
      );
      return;
    }
    const fallbackN =
      botDrawer.mode === "create" ? botDrawer.nextVersion : botDrawer.bot.version_number;
    const versionNumber = toPositiveVersion(bForm.versionNumber, fallbackN);
    const name = bForm.name.trim() || `Bot v${versionNumber}`;
    const payload: Record<string, unknown> = {
      name,
      version_number: versionNumber,
      content: code,
      trading_pair: pair,
    };
    if (botDrawer.mode === "edit" && botDrawer.bot.status === "error") {
      payload.status = "stopped";
      payload.last_error = null;
      payload.last_error_at = null;
    }
    const botId = botDrawer.mode === "edit" ? botDrawer.bot.id : null;
    logBotSave("start", {
      mode: botDrawer.mode,
      strategyId: botDrawer.strategyId,
      botId,
      contentChars: code.length,
      pair,
      versionNumber,
      name,
      clearErrorToStopped: botDrawer.mode === "edit" && botDrawer.bot.status === "error",
    });
    let saveOk = false;
    try {
      if (botDrawer.mode === "create") {
        const insertMarket = pair.endsWith(".P") ? { market_type: "linear" as const } : {};
        const { data, error } = await s
          .from("bots")
          .insert({
            strategy_id: botDrawer.strategyId,
            status: "stopped",
            ...insertMarket,
            ...payload,
          })
          .select("id");
        if (error) {
          const msg = formatPostgrestError(error);
          setLoadError(msg);
          setBotSaveError(msg);
          logBotSave("insert_fail", { error, data, devtools: "F12 → Console → [algoshift" });
        } else {
          logBotSave("insert_ok", { id: data?.[0]?.id, contentChars: code.length });
          saveOk = true;
        }
      } else {
        const { data, error } = await s
          .from("bots")
          .update(payload)
          .eq("id", botDrawer.bot.id)
          .select("id, status, updated_at, last_error");
        if (error) {
          const msg = formatPostgrestError(error);
          setLoadError(msg);
          setBotSaveError(msg);
          logBotSave("update_fail", {
            botId: botDrawer.bot.id,
            error,
            data,
            devtools: "F12 → Console → [algoshift",
          });
        } else {
          logBotSave("update_ok", { botId: botDrawer.bot.id, row: data?.[0] });
          saveOk = true;
        }
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setLoadError(msg);
      setBotSaveError(msg);
      logBotSave("exception", { err: e });
    }
    if (saveOk) {
      setBotDrawer(null);
      void refetch();
    }
  };

  const setBotStatus = async (botId: string, status: BotStatus) => {
    if (!canUseDb) {
      return;
    }
    setLoadError(null);
    console.info("[algoshift Strategies] setBotStatus click", { botId, to: status });
    const res = await updateBotRuntimeStatus(botId, status);
    if (!res.ok) {
      setLoadError(res.message);
      return;
    }
    void refetch();
  };

  const onDeleteBot = async (botId: string) => {
    if (!canUseDb) {
      return;
    }
    if (!window.confirm("Delete this bot?")) {
      return;
    }
    const s = getSupabaseClient()!;
    const { error } = await s.from("bots").delete().eq("id", botId);
    if (error) {
      setLoadError(error.message);
      return;
    }
    void refetch();
  };

  const openNewBot = (st: StrategyWithBots) => {
    setBotSaveError(null);
    const maxN =
      st.bots.length > 0 ? Math.max(...st.bots.map((b) => b.version_number)) : 0;
    setBotDrawer({ mode: "create", strategyId: st.id, nextVersion: maxN + 1 || 1 });
  };

  const openBotForEdit = (strategyId: string, bot: BotRow) => {
    setBotSaveError(null);
    setBotDrawer({ mode: "edit", strategyId, bot });
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

          {loading && rows.length === 0 && <p className="text-[#666]">Loading strategies…</p>}

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
                        {isOpen ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </button>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[13px] font-semibold leading-tight text-[#ededed]">
                          {st.name}
                        </div>
                        <div className="mt-0.5 font-mono text-[11px] text-[#666]">
                          {st.bots.length} bot{st.bots.length === 1 ? "" : "s"} ·{" "}
                          <Link to="/" className="text-[#0070f3] hover:underline">
                            Home
                          </Link>{" "}
                          · runtime below
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
                          onClick={() => void onDeleteStrategy(st.id, st.bots.length)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                    {isOpen ? (
                      <div className="border-t border-white/[0.04]">
                        <div className="flex items-center justify-between border-b border-white/[0.04] px-3.5 py-2">
                          <span className="font-mono text-[11px] text-[#666]">BOTS</span>
                          <button
                            type="button"
                            className="inline-flex h-7 items-center gap-1 rounded-md bg-white/[0.06] px-2 text-[12px] text-[#ededed] hover:bg-white/[0.1]"
                            onClick={() => openNewBot(st)}
                          >
                            <Plus className="h-3.5 w-3.5" />
                            Add bot
                          </button>
                        </div>
                        {st.bots.length === 0 ? (
                          <p className="px-3.5 py-3 text-[13px] text-[#666]">No bots yet.</p>
                        ) : (
                          <ul className="divide-y divide-white/[0.04]">
                            {st.bots.map((b) => (
                              <li
                                key={b.id}
                                className="flex items-start gap-3 px-3.5 py-2.5 text-[13px]"
                              >
                                <div className="w-8 shrink-0 text-center font-mono text-[12px] text-[#dedede]">
                                  {b.version_number}
                                </div>
                                <div className="min-w-0 flex-1">
                                  <div className="truncate font-medium text-[#ededed]">{b.name}</div>
                                  <div className="mb-0.5 mt-0.5 flex flex-wrap items-center gap-2">
                                    <span className={runtimeBadge(b.status)}>
                                      {runtimeLabel[b.status]}
                                    </span>
                                    <span className="font-mono text-[11px] text-[#666]">
                                      {b.trading_pair}
                                    </span>
                                    <span className="font-mono text-[11px] text-[#666]">
                                      {(b.content || "").length.toLocaleString()} chars
                                    </span>
                                  </div>
                                  <p className="text-[11px] text-[#666]">
                                    <span className="font-mono text-[10px] text-[#555]">{b.id}</span>
                                  </p>
                                  {b.status === "error" && (
                                    <p className="mt-1 text-[11px] text-amber-400/90">
                                      Em erro: grava o código (Save) — fica Stopped e limpa o erro — depois Start
                                      para Running. Ou só Start se o código já estiver ok.
                                    </p>
                                  )}
                                </div>
                                <div className="flex shrink-0 flex-col items-end gap-1.5 sm:flex-row sm:items-center">
                                  <div className="flex flex-wrap justify-end gap-1">
                                    {b.status !== "running" && b.status !== "paused" && (
                                      <button
                                        type="button"
                                        className="rounded border border-white/15 bg-white/[0.08] px-2 py-0.5 text-[11px] text-[#ededed] hover:bg-white/12"
                                        onClick={() => void setBotStatus(b.id, "running")}
                                      >
                                        Start
                                      </button>
                                    )}
                                    {b.status === "running" && (
                                      <>
                                        <button
                                          type="button"
                                          className="rounded border border-white/15 bg-white/[0.08] px-2 py-0.5 text-[11px] text-[#ededed] hover:bg-white/12"
                                          onClick={() => void setBotStatus(b.id, "paused")}
                                        >
                                          Pause
                                        </button>
                                        <button
                                          type="button"
                                          className="rounded border border-rose-500/50 bg-rose-500/10 px-2 py-0.5 text-[11px] text-rose-200 hover:bg-rose-500/20"
                                          onClick={() => void setBotStatus(b.id, "stopped")}
                                        >
                                          Stop
                                        </button>
                                      </>
                                    )}
                                    {b.status === "paused" && (
                                      <>
                                        <button
                                          type="button"
                                          className="rounded border border-white/15 bg-white/[0.08] px-2 py-0.5 text-[11px] text-[#ededed] hover:bg-white/12"
                                          onClick={() => void setBotStatus(b.id, "running")}
                                        >
                                          Resume
                                        </button>
                                        <button
                                          type="button"
                                          className="rounded border border-rose-500/50 bg-rose-500/10 px-2 py-0.5 text-[11px] text-rose-200 hover:bg-rose-500/20"
                                          onClick={() => void setBotStatus(b.id, "stopped")}
                                        >
                                          Stop
                                        </button>
                                      </>
                                    )}
                                  </div>
                                  <div className="flex gap-0.5">
                                    <button
                                      type="button"
                                      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-[#919191] hover:bg-white/[0.05] hover:text-[#ededed]"
                                      title="Edit bot"
                                      onClick={() => openBotForEdit(st.id, b)}
                                    >
                                      <Pencil className="h-3.5 w-3.5" />
                                    </button>
                                    <button
                                      type="button"
                                      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-[#919191] hover:bg-white/[0.05] hover:text-rose-400"
                                      title="Delete bot"
                                      onClick={() => void onDeleteBot(b.id)}
                                    >
                                      <Trash2 className="h-3.5 w-3.5" />
                                    </button>
                                  </div>
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
        open={botDrawer !== null}
        onOpenChange={(o) => {
          if (!o) {
            setBotDrawer(null);
            setBotSaveError(null);
          }
        }}
        widthClassName="w-full max-w-5xl"
        title={botDrawer?.mode === "create" ? "New bot" : "Edit bot"}
        footer={
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="h-8 rounded-md px-3 text-[13px] text-[#919191] hover:bg-white/[0.05] hover:text-[#ededed]"
              onClick={() => setBotDrawer(null)}
            >
              Cancel
            </button>
            <button type="button" className="h-8 rounded-md bg-[#ededed] px-3 text-[13px] font-medium text-[#0a0a0a] hover:bg-white" onClick={() => void onSaveBot()}>
              Save
            </button>
          </div>
        }
      >
        {botSaveError && (
          <div className="mb-3 rounded-md border border-rose-500/30 bg-rose-950/40 px-3 py-2 text-[12px] text-rose-200/95">
            <p className="font-medium text-rose-100/95">Falha ao salvar (ver Consola: F12 → aba Consola, filtrar "algoshift")</p>
            <p className="mt-1 whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-rose-200/90">
              {botSaveError}
            </p>
          </div>
        )}
        <p className="mb-2 text-[11px] text-[#666]">
          Dica de debug: com o drawer aberto, <span className="font-mono">Save</span> e um erro: DevTools
          (⌥⌘I) → <span className="font-mono">Console</span> → procura{" "}
          <span className="font-mono text-[#aaa]">[algoshift Strategies/bot save]</span>.
        </p>
        <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-[12px] text-[#666]">Name</label>
            <input
              className="w-full rounded-md border-0 bg-[#111] px-3 py-2 text-[13px] text-[#ededed] ring-1 ring-inset ring-white/[0.1] focus:outline-none focus:ring-2 focus:ring-[hsl(212,100%,48%)]"
              value={bForm.name}
              onChange={(e) => setBForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="Bot display name"
            />
          </div>
          <div>
            <label className="mb-1 block text-[12px] text-[#666]">Version #</label>
            <input
              type="number"
              min={1}
              step={1}
              className="w-full rounded-md border-0 bg-[#111] px-3 py-2 text-[13px] text-[#ededed] ring-1 ring-inset ring-white/[0.1] focus:outline-none focus:ring-2 focus:ring-[hsl(212,100%,48%)]"
              value={bForm.versionNumber < 1 ? 1 : bForm.versionNumber}
              onChange={(e) => {
                const raw = e.target.value;
                const n = raw === "" ? 1 : Number.parseInt(raw, 10);
                setBForm((f) => ({
                  ...f,
                  versionNumber: Number.isFinite(n) && n > 0 ? n : 1,
                }));
              }}
            />
          </div>
          <div className="sm:col-span-2">
            <label className="mb-1 block text-[12px] text-[#666]">Trading pair</label>
            <input
              className="w-full rounded-md border-0 bg-[#111] px-3 py-2 font-mono text-[13px] text-[#ededed] ring-1 ring-inset ring-white/[0.1] focus:outline-none focus:ring-2 focus:ring-[hsl(212,100%,48%)]"
              value={bForm.tradingPair}
              onChange={(e) => setBForm((f) => ({ ...f, tradingPair: e.target.value }))}
              placeholder="BTCUSDT.P"
            />
          </div>
        </div>
        <p className="mb-3 text-[11px] text-[#666]">
          Same string Hub publishes on <span className="font-mono">market_data:…</span> (must match worker
          subscription). <span className="font-mono">.P</span> = linear perp; plain{" "}
          <span className="font-mono">BTCUSDT</span> uses bot <span className="font-mono">market_type</span> in DB
          (spot vs linear). Set <span className="font-mono">market_type</span> in Supabase if needed.
        </p>
        <p className="mb-1 text-[11px] text-[#666]">
          Order size: worker reads <span className="font-mono">signal_amount</span> /{" "}
          <span className="font-mono">order_size</span> / <span className="font-mono">amount</span> on the strategy
          instance, or <span className="font-mono">get_signal_amount()</span>. Optional fallback:{" "}
          <span className="font-mono">bots.params</span>. Hub risk caps (if used):{" "}
          <span className="font-mono">max_order_size</span>, <span className="font-mono">max_notional_usd</span>,{" "}
          <span className="font-mono">max_open_positions</span> in params.
        </p>
        <p className="mb-1 text-[11px] text-[#666]">
          Start/Pause/Stop on this page or <Link to="/" className="text-[#0070f3] hover:underline">Home</Link>.
          Deployed worker uses <span className="font-mono">BOT_ID</span> = this bot&apos;s id (process stays up on Stop; set Running again to resume).
        </p>
        <label className="mb-1 block text-[12px] text-[#666]">Content (python)</label>
        <textarea
          key={
            botDrawer
              ? botDrawer.mode === "create"
                ? `c-${botDrawer.strategyId}-${botDrawer.nextVersion}`
                : `e-${botDrawer.bot.id}`
              : "closed"
          }
          ref={botCodeRef}
          defaultValue={botDrawer?.mode === "edit" ? botDrawer.bot.content : ""}
          className={cn(
            "h-[min(80vh,1200px)] w-full min-h-[20rem] resize-y overflow-auto",
            "rounded-md border-0 bg-[#0a0a0a] px-3 py-2",
            "font-mono text-[12px] leading-[1.4] text-[#e4e4e4]",
            "whitespace-pre ring-1 ring-inset ring-white/[0.1] focus:outline-none focus:ring-2",
            "focus:ring-[hsl(212,100%,48%)]",
          )}
          placeholder="# Strategy class or def on_tick(market_data)"
          spellCheck={false}
          autoComplete="off"
        />
      </Drawer>
    </DashboardLayout>
  );
};

export default StrategiesPage;
