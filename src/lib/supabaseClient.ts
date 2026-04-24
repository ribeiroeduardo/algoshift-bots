import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { Database } from "@/types/database";

let client: SupabaseClient<Database> | null = null;

export const isSupabaseEnabled = (): boolean => {
  const url = import.meta.env.VITE_SUPABASE_URL;
  const key = import.meta.env.VITE_SUPABASE_ANON_KEY;
  return Boolean(url && String(url).trim() && key && String(key).trim());
};

export const getSupabaseClient = (): SupabaseClient<Database> | null => {
  if (!isSupabaseEnabled()) {
    return null;
  }
  if (!client) {
    const url = import.meta.env.VITE_SUPABASE_URL;
    const key = import.meta.env.VITE_SUPABASE_ANON_KEY;
    client = createClient<Database>(url, key);
  }
  return client;
};
