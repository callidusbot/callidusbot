export interface ActiveEvent {
  event_id: string;
  template_key: string;
  template_title: string;
  started_by: number;
  started_by_name: string;
  started_by_avatar: string;
  started_at: number;
  thread_id: number;
  participants: number[];
  participant_count: number;
  status: "active" | "closed";
}

export interface DynamicSheet {
  name: string;
  sheet_url_or_id: string;
  tab: string;
  emoji: string;
  type: "content" | "mass";
  slug: string;
}

export interface ContentRole {
  role_name: string;
  capacity: number;
}

export interface ContentTemplate {
  key: string;
  title: string;
  subtitle: string;
  thread_name: string;
  emoji: string;
  category: "content" | "mass";
  order: number;
  roles: ContentRole[];
  base_points: number;
  loot_bonus_points: number;
}

export interface PuanConfig {
  voice: {
    puan_per_minute: number;
    daily_max: number;
    warning_threshold: number;
    kick_threshold: number;
  };
  content: {
    default_base_points: number;
    default_loot_bonus_points: number;
  };
  mass: {
    default_base_points: number;
    default_loot_bonus_points: number;
  };
}

export const DEFAULT_PUAN_CONFIG: PuanConfig = {
  voice: {
    puan_per_minute: 0.1,
    daily_max: 20,
    warning_threshold: 120,
    kick_threshold: 240,
  },
  content: {
    default_base_points: 0,
    default_loot_bonus_points: 0,
  },
  mass: {
    default_base_points: 0,
    default_loot_bonus_points: 0,
  },
};
