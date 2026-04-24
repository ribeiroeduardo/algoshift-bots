import { getSupabaseClient } from "@/lib/supabaseClient";
import type { BotStatus } from "@/types/database";

const TAG = "[algoshift bot status]";

type Ok = { ok: true; row: { id: string; status: string; updated_at: string } };
type Fail = { ok: false; message: string; rawError?: { message: string; code?: string; details?: string; hint?: string } };
export type BotStatusUpdateResult = Ok | Fail;

/**
 * Set `public.bots.status` and return the row, or a clear error.
 * Use `.select()` so PostgREST returns 0 rows when RLS/ID match fails (otherwise "success" with no change).
 */
export async function updateBotRuntimeStatus(
  botId: string,
  status: BotStatus,
): Promise<BotStatusUpdateResult> {
  const c = getSupabaseClient();
  if (!c) {
    const message = "Supabase client not configured (VITE_SUPABASE_*)";
    console.warn(TAG, "fail", { botId, status, message });
    return { ok: false, message };
  }
  console.info(TAG, "request", { botId, status });
  const { data, error } = await c
    .from("bots")
    .update({ status })
    .eq("id", botId)
    .select("id, status, updated_at");

  if (error) {
    console.error(TAG, "rejected", { botId, status, error });
    return { ok: false, message: formatPgrstError(error), rawError: error };
  }
  const row = data?.[0];
  if (!row) {
    const message =
      "0 rows updated — check bot id, or RLS policy on public.bots for your anon key.";
    console.error(TAG, "0 rows (silent no-op)", { botId, status, data });
    return { ok: false, message };
  }
  console.info(TAG, "ok", row);
  return { ok: true, row: row as Ok["row"] };
}

function formatPgrstError(e: { message: string; code?: string; details?: string; hint?: string }) {
  return [e.message, e.hint && `hint: ${e.hint}`, e.details && `details: ${e.details}`]
    .filter(Boolean)
    .join(" | ");
}
