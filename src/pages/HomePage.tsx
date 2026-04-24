import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Bot } from "lucide-react";
import { Link } from "react-router-dom";
import { DashboardLayout } from "@/components/dashboard/DashboardLayout";
import { getSupabaseClient, isSupabaseEnabled } from "@/lib/supabaseClient";
import { cn } from "@/lib/utils";
import type { BotRow, BotStatus } from "@/types/database";

type BotWithHb = BotRow & {
  bot_heartbeats:
    | {
        last_heartbeat_at: string;
        last_tick_at: string | null;
        last_signal_at: string | null;
        worker_version: string | null;
      }
    | null
    | Array<{
        last_heartbeat_at: string;
        last_tick_at: string | null;
        last_signal_at: string | null;
        worker_version: string | null;
      }>;
  last_open?: { status: string; par_negociacao: string; opened_at: string | null } | null;
};

const ActBtn = ({
  children,
  onClick,
  className,
}: {
  children: ReactNode;
  onClick: () => void;
  className?: string;
}) => (
  <button
    type="button"
    onClick={onClick}
    className={cn(
      "rounded border border-white/15 bg-white/[0.08] px-2.5 py-1 text-xs text-[#ededed] hover:bg-white/12",
      className,
    )}
  >
    {children}
  </button>
);

const statusLabel: Record<BotStatus, string> = {
  stopped: "Stopped",
  running: "Running",
  paused: "Paused",
  error: "Error",
};

const setStatus = (botId: string, s: BotStatus) => {
  const c = getSupabaseClient();
  if (!c) return Promise.resolve();
  return c.from("bots").update({ status: s } as { status: BotStatus }).eq("id", botId);
};

const HomePage = () => {
  const [rows, setRows] = useState<BotWithHb[]>([]);
  const [loading, setLoading] = useState(true);
  const enabled = isSupabaseEnabled();
  const load = useCallback(async () => {
    if (!getSupabaseClient()) {
      setLoading(false);
      return;
    }
    setLoading(true);
    const c = getSupabaseClient()!;
    const { data, error } = await c.from("bots").select("*, bot_heartbeats(*)").order("name");
    if (error) {
      console.error(error);
      setRows([]);
    } else {
      const withLast = (data || []) as BotWithHb[];
      for (const b of withLast) {
        const { data: t } = await c
          .from("trades")
          .select("status, par_negociacao, opened_at")
          .eq("bot_id", b.id)
          .eq("status", "OPEN")
          .order("opened_at", { ascending: false })
          .limit(1);
        b.last_open = t?.[0] ?? null;
      }
      setRows(withLast);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    void load();
    const t = setInterval(() => void load(), 20_000);
    return () => clearInterval(t);
  }, [enabled, load]);

  if (!enabled) {
    return (
      <DashboardLayout title="Home">
        <p className="p-4 text-sm text-[#919191]">
          Supabase env missing — set <code className="text-[#ededed]">VITE_SUPABASE_URL</code> +{" "}
          <code className="text-[#ededed]">VITE_SUPABASE_ANON_KEY</code> for bots.
        </p>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout title="Home">
      <div className="flex min-h-0 flex-col gap-3 p-4 text-[13px]">
        <h1 className="text-sm font-medium text-[#ededed]">Bots</h1>
        {loading && <p className="text-[#919191]">Loading…</p>}
        {!loading && rows.length === 0 && (
          <div
            className={cn(
              "mx-auto flex max-w-md flex-col items-center text-center",
              "rounded-lg bg-[#1a1a1a] px-8 py-8 ring-1 ring-inset ring-white/[0.06]",
            )}
          >
            <div className="mb-3 flex h-12 w-12 items-center justify-center text-[#ededed]" aria-hidden>
              <Bot className="h-7 w-7" strokeWidth={1.75} />
            </div>
            <p className="text-[#919191]">No rows in `bots` yet, or not migrated. Add a bot under Strategies, or use SQL.</p>
            <Link to="/strategies" className="mt-2 text-[#0070f3] hover:underline">
              Strategies
            </Link>
          </div>
        )}
        <ul className="space-y-3">
          {rows.map((b) => {
            const hb = Array.isArray(b.bot_heartbeats) ? b.bot_heartbeats[0] : b.bot_heartbeats;
            return (
              <li
                key={b.id}
                className="rounded-lg border border-white/[0.08] bg-[#1a1a1a] p-3 text-left"
              >
                <div className="font-medium text-[#ededed]">{b.name}</div>
                <div className="mt-1 text-xs text-[#919191]">
                  {b.trading_pair} · {statusLabel[b.status]}
                </div>
                {b.last_error && b.status === "error" && (
                  <p className="mt-1 text-xs text-amber-400/90">{b.last_error}</p>
                )}
                {hb?.last_heartbeat_at && (
                  <p className="mt-1 text-xs text-[#707070]">
                    heartbeat: {new Date(hb.last_heartbeat_at).toLocaleString()}
                    {hb.worker_version ? ` · ${hb.worker_version}` : ""}
                  </p>
                )}
                {b.last_open && (
                  <p className="mt-1 text-xs text-[#707070]">
                    last open: {b.last_open.par_negociacao} {b.last_open.opened_at || ""}
                  </p>
                )}
                <div className="mt-2 flex flex-wrap gap-2">
                  {b.status !== "running" && b.status !== "paused" && (
                    <ActBtn
                      onClick={() => {
                        void (async () => {
                          const r = setStatus(b.id, "running");
                          if (r) await r;
                          await load();
                        })();
                      }}
                    >
                      Start
                    </ActBtn>
                  )}
                  {b.status === "running" && (
                    <>
                      <ActBtn
                        onClick={() => {
                          void (async () => {
                            const r = setStatus(b.id, "paused");
                            if (r) await r;
                            await load();
                          })();
                        }}
                      >
                        Pause
                      </ActBtn>
                      <ActBtn
                        className="border-rose-500/50 text-rose-200 hover:bg-rose-500/20"
                        onClick={() => {
                          void (async () => {
                            const r = setStatus(b.id, "stopped");
                            if (r) await r;
                            await load();
                          })();
                        }}
                      >
                        Stop
                      </ActBtn>
                    </>
                  )}
                  {b.status === "paused" && (
                    <>
                      <ActBtn
                        onClick={() => {
                          void (async () => {
                            const r = setStatus(b.id, "running");
                            if (r) await r;
                            await load();
                          })();
                        }}
                      >
                        Resume
                      </ActBtn>
                      <ActBtn
                        className="border-rose-500/50 text-rose-200 hover:bg-rose-500/20"
                        onClick={() => {
                          void (async () => {
                            const r = setStatus(b.id, "stopped");
                            if (r) await r;
                            await load();
                          })();
                        }}
                      >
                        Stop
                      </ActBtn>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        <p className="text-xs text-[#5c5c5c]">Refresh ~20s. Use Railway: Hub + Worker per `BOT_ID` (see /railway).</p>
      </div>
    </DashboardLayout>
  );
};

export default HomePage;
