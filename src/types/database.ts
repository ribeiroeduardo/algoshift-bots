/** Lifecycle for bot code (draft / active / archived). Postgres enum: strategy_version_status */
export type BotCodeStatus = "draft" | "active" | "archived";

export type BotStatus = "stopped" | "running" | "paused" | "error";

export type StrategyRow = {
  id: string;
  user_id: string | null;
  name: string;
  created_at: string;
  updated_at: string;
};

export type BotRow = {
  id: string;
  name: string;
  strategy_id: string;
  content: string;
  version_number: number;
  code_status: BotCodeStatus;
  trading_pair: string;
  exchange: string;
  market_type: "spot" | "linear" | "inverse";
  status: BotStatus;
  params: Record<string, unknown>;
  last_error: string | null;
  last_error_at: string | null;
  created_at: string;
  updated_at: string;
};

export type BotHeartbeatRow = {
  bot_id: string;
  last_heartbeat_at: string;
  worker_instance_id: string | null;
  worker_version: string | null;
  last_tick_at: string | null;
  last_signal_at: string | null;
  updated_at: string;
};

export type TradeRow = {
  id: string;
  signal_id: string | null;
  bot_id: string | null;
  /** Legacy name; stores bot id for code snapshot when filled */
  versao_id: string | null;
  par_negociacao: string;
  direcao: string;
  preco_entrada: number | null;
  resultado: string | null;
  exchange_order_id: string | null;
  quantity: number | null;
  notional_usd: number | null;
  fee_usd: number | null;
  exit_price: number | null;
  pnl_usd: number | null;
  opened_at: string | null;
  closed_at: string | null;
  status: "OPEN" | "CLOSED" | "CANCELED" | "REJECTED";
  created_at: string;
  updated_at: string;
};

type EmptyObject = { [_ in never]: never };

export type Database = {
  public: {
    Tables: {
      strategies: {
        Row: StrategyRow;
        Insert: {
          id?: string;
          user_id?: string | null;
          name: string;
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          id?: string;
          user_id?: string;
          name?: string;
          created_at?: string;
          updated_at?: string;
        };
        Relationships: [];
      };
      bots: {
        Row: BotRow;
        Insert: {
          id?: string;
          name: string;
          strategy_id: string;
          content?: string;
          version_number?: number;
          code_status?: BotCodeStatus;
          trading_pair: string;
          exchange?: string;
          market_type?: "spot" | "linear" | "inverse";
          status?: BotStatus;
          params?: Record<string, unknown>;
          last_error?: string | null;
          last_error_at?: string | null;
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          id?: string;
          name?: string;
          strategy_id?: string;
          content?: string;
          version_number?: number;
          code_status?: BotCodeStatus;
          trading_pair?: string;
          exchange?: string;
          market_type?: "spot" | "linear" | "inverse";
          status?: BotStatus;
          params?: Record<string, unknown>;
          last_error?: string | null;
          last_error_at?: string | null;
          created_at?: string;
          updated_at?: string;
        };
        Relationships: [];
      };
      bot_heartbeats: {
        Row: BotHeartbeatRow;
        Insert: {
          bot_id: string;
          last_heartbeat_at?: string;
          worker_instance_id?: string | null;
          worker_version?: string | null;
          last_tick_at?: string | null;
          last_signal_at?: string | null;
          updated_at?: string;
        };
        Update: {
          bot_id?: string;
          last_heartbeat_at?: string;
          worker_instance_id?: string | null;
          worker_version?: string | null;
          last_tick_at?: string | null;
          last_signal_at?: string | null;
          updated_at?: string;
        };
        Relationships: [
          {
            foreignKeyName: "bot_heartbeats_bot_id_fkey";
            columns: ["bot_id"];
            isOneToOne: true;
            referencedRelation: "bots";
            referencedColumns: ["id"];
          },
        ];
      };
      trades: {
        Row: TradeRow;
        Insert: {
          id?: string;
          signal_id?: string | null;
          bot_id?: string | null;
          versao_id?: string | null;
          par_negociacao: string;
          direcao: string;
          preco_entrada?: number | null;
          resultado?: string | null;
          exchange_order_id?: string | null;
          quantity?: number | null;
          notional_usd?: number | null;
          fee_usd?: number | null;
          exit_price?: number | null;
          pnl_usd?: number | null;
          opened_at?: string | null;
          closed_at?: string | null;
          status?: "OPEN" | "CLOSED" | "CANCELED" | "REJECTED";
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          id?: string;
          signal_id?: string | null;
          bot_id?: string | null;
          versao_id?: string | null;
          par_negociacao?: string;
          direcao?: string;
          preco_entrada?: number | null;
          resultado?: string | null;
          exchange_order_id?: string | null;
          quantity?: number | null;
          notional_usd?: number | null;
          fee_usd?: number | null;
          exit_price?: number | null;
          pnl_usd?: number | null;
          opened_at?: string | null;
          closed_at?: string | null;
          status?: "OPEN" | "CLOSED" | "CANCELED" | "REJECTED";
          created_at?: string;
          updated_at?: string;
        };
        Relationships: [];
      };
    };
    Views: EmptyObject;
    Functions: EmptyObject;
    Enums: {
      strategy_version_status: BotCodeStatus;
      bot_status: BotStatus;
    };
    CompositeTypes: EmptyObject;
  };
};
