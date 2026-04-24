import type { User } from "@supabase/supabase-js";
import { useCallback, useEffect, useState } from "react";
import { getSupabaseClient, isSupabaseEnabled } from "@/lib/supabaseClient";

type AuthState = {
  user: User | null;
  loading: boolean;
};

export const useAuthSession = () => {
  const [state, setState] = useState<AuthState>({ user: null, loading: true });

  useEffect(() => {
    if (!isSupabaseEnabled()) {
      setState({ user: null, loading: false });
      return;
    }
    const supabase = getSupabaseClient()!;
    void supabase.auth.getUser().then(({ data }) => {
      setState({ user: data.user ?? null, loading: false });
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) => {
      setState({ user: session?.user ?? null, loading: false });
    });
    return () => {
      sub.subscription.unsubscribe();
    };
  }, []);

  const signInWithGoogle = useCallback(async () => {
    if (!isSupabaseEnabled() || !getSupabaseClient()) {
      return;
    }
    const { error } = await getSupabaseClient()!.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: globalThis.location.origin + "/" },
    });
    if (error) {
      console.error(error);
    }
  }, []);

  const signOut = useCallback(async () => {
    if (!isSupabaseEnabled() || !getSupabaseClient()) {
      return;
    }
    await getSupabaseClient()!.auth.signOut();
  }, []);

  return { user: state.user, loading: state.loading, signInWithGoogle, signOut };
};
