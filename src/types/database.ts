export type StrategyVersionStatus = "draft" | "active" | "archived";

export type StrategyRow = {
  id: string;
  user_id: string | null;
  name: string;
  created_at: string;
  updated_at: string;
};

export type StrategyVersionRow = {
  id: string;
  strategy_id: string;
  version_number: number;
  content: string;
  status: StrategyVersionStatus;
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
      strategy_versions: {
        Row: StrategyVersionRow;
        Insert: {
          id?: string;
          strategy_id: string;
          version_number: number;
          content?: string;
          status?: StrategyVersionStatus;
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          id?: string;
          strategy_id?: string;
          version_number?: number;
          content?: string;
          status?: StrategyVersionStatus;
          created_at?: string;
          updated_at?: string;
        };
        Relationships: [
          {
            foreignKeyName: "strategy_versions_strategy_id_fkey";
            columns: ["strategy_id"];
            isOneToOne: false;
            referencedRelation: "strategies";
            referencedColumns: ["id"];
          },
        ];
      };
    };
    Views: EmptyObject;
    Functions: EmptyObject;
    Enums: {
      strategy_version_status: StrategyVersionStatus;
    };
    CompositeTypes: EmptyObject;
  };
};
