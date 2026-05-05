export type ApiState<T> =
  | {
      ok: true;
      data: T;
      error?: never;
    }
  | {
      ok: false;
      data: T;
      error: string;
    };

export type DashboardSummary = {
  platform_count?: number;
  subscription_count?: number;
  active_subscription_count?: number;
};

export type PlatformGroup = {
  label?: string;
  platform?: string;
  subscription_count?: number;
  active_subscription_count?: number;
  subscriptions?: Array<{
    display_name?: string;
    platform_label?: string;
    status?: string;
    source_type?: string;
    source_url?: string;
    updated_at?: string;
  }>;
};

export type ManualSubmission = {
  id?: number;
  url?: string;
  request_url?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
  title?: string;
  item_id?: string;
  dedupe_action?: string;
};

export type CollectionsPayload = {
  summary?: DashboardSummary;
  platform_groups?: PlatformGroup[];
  manual_submission_summary?: {
    recent_count?: number;
    active_count?: number;
    total_count?: number;
    running_count?: number;
    success_count?: number;
    failed_count?: number;
  };
  manual_submissions?: ManualSubmission[];
};

export type StatusCheck = {
  id?: string;
  title?: string;
  status_tone?: string;
  status_label?: string;
  summary?: string;
  detail_lines?: string[];
};

export type ServiceStatusPayload = {
  overall_status_tone?: string;
  overall_status_label?: string;
  checks?: StatusCheck[];
  rss_poll?: {
    run_finished_at?: string;
    run_finished_at_raw?: string;
    run_status?: string;
    source_count?: number;
    wrote_count?: number;
    error_count?: number;
  };
  mainline_llm?: {
    configured_model?: string;
    live_model?: string;
    configured_reasoning_effort?: string;
    live_reasoning_effort?: string;
    configured_thinking_type?: string;
    live_thinking_type?: string;
  };
};

export type LlmTokenUsage = {
  calls?: number;
  usage_missing?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cached_prompt_tokens?: number;
  prompt_cache_hit_tokens?: number;
  prompt_cache_miss_tokens?: number;
  reasoning_tokens?: number;
};

export type RssPollSummary = {
  execution_id?: string;
  workflow?: string;
  workflow_id?: string;
  run_started_at?: string;
  run_finished_at?: string;
  source_count?: number;
  success_source_count?: number;
  failed_source_count?: number;
  items_seen?: number;
  items_selected_for_processing?: number;
  items_written?: number;
  poll_runs_version?: number;
  llm_usage?: LlmTokenUsage;
  llm_calls?: number;
  llm_usage_missing?: number;
  llm_prompt_tokens?: number;
  llm_completion_tokens?: number;
  llm_total_tokens?: number;
};

export type TokenHistoryPoint = {
  date?: string;
  label?: string;
  execution_count?: number;
  llm_calls?: number;
  llm_usage_missing?: number;
  llm_prompt_tokens?: number;
  llm_completion_tokens?: number;
  llm_total_tokens?: number;
};

export type RssPollPayload = {
  ok?: boolean;
  found?: boolean;
  file_path?: string;
  poll?: RssPollSummary;
  llm_usage?: LlmTokenUsage;
  llm_calls?: number;
  llm_usage_missing?: number;
  llm_prompt_tokens?: number;
  llm_completion_tokens?: number;
  llm_total_tokens?: number;
  token_history?: TokenHistoryPoint[];
  run_started_at?: string;
  run_finished_at?: string;
  sources?: Array<{
    source_name?: string;
    source_type?: string;
    feed_url?: string;
    rss_status?: string;
    transcript_status?: string;
    item_count?: number;
    new_item_count?: number;
    wrote_count?: number;
    qdrant_commit_count?: number;
    llm_usage?: LlmTokenUsage;
    llm_calls?: number;
    llm_usage_missing?: number;
    llm_prompt_tokens?: number;
    llm_completion_tokens?: number;
    llm_total_tokens?: number;
    sample_titles?: string[];
    new_titles?: string[];
    wrote_paths?: string[];
  }>;
};

const FALLBACK_COLLECTIONS: CollectionsPayload = {
  summary: {
    platform_count: 0,
    subscription_count: 0,
    active_subscription_count: 0,
  },
  platform_groups: [],
  manual_submission_summary: {
    total_count: 0,
    recent_count: 0,
    active_count: 0,
    running_count: 0,
    success_count: 0,
    failed_count: 0,
  },
  manual_submissions: [],
};

const FALLBACK_STATUS: ServiceStatusPayload = {
  overall_status_tone: "muted",
  overall_status_label: "后端未连接",
  checks: [
    {
      id: "collector-web-api",
      title: "Collector Web API",
      status_tone: "muted",
      status_label: "离线",
      summary: "Next 只读前端已加载，但还没有连接到 FastAPI 数据源。",
      detail_lines: ["默认数据源: http://127.0.0.1:8300"],
    },
  ],
};

const FALLBACK_RSS_POLL: RssPollPayload = {
  ok: false,
  found: false,
  sources: [],
};

function apiBaseUrl() {
  return (
    process.env.COLLECTOR_WEB_API_BASE_URL?.replace(/\/$/, "") ||
    "http://127.0.0.1:18300"
  );
}

async function getJson<T>(path: string, fallback: T): Promise<ApiState<T>> {
  try {
    const response = await fetch(`${apiBaseUrl()}${path}`, {
      cache: "no-store",
      headers: {
        Accept: "application/json",
      },
    });

    if (!response.ok) {
      return {
        ok: false,
        data: fallback,
        error: `FastAPI returned HTTP ${response.status}`,
      };
    }

    return {
      ok: true,
      data: (await response.json()) as T,
    };
  } catch (error) {
    return {
      ok: false,
      data: fallback,
      error: error instanceof Error ? error.message : "FastAPI request failed",
    };
  }
}

export function getCollectorApiBaseUrl() {
  return apiBaseUrl();
}

export function getCollections() {
  return getJson<CollectionsPayload>("/api/collections", FALLBACK_COLLECTIONS);
}

export function getServiceStatus() {
  return getJson<ServiceStatusPayload>("/api/status", FALLBACK_STATUS);
}

export function getLatestRssPoll() {
  return getJson<RssPollPayload>("/api/rss-poll/latest", FALLBACK_RSS_POLL);
}
