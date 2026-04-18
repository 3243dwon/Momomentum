// Mirrors the JSON shapes produced by the Python scanner.
// Keep these in sync with scanner/render.py and the LLM tier outputs.

export type Window = 'RTH' | 'AH_PRE' | 'AH_POST' | 'OVERNIGHT' | 'WEEKEND';
export type Impact = 'high' | 'medium' | 'low';
export type Confidence = 'high' | 'medium' | 'low';
export type Verdict = 'news_explains_move' | 'partial_explanation' | 'move_unexplained_by_news';
export type Horizon = 'intraday' | 'days' | 'weeks' | 'months';

export interface Synthesis {
  summary: string;
  supporting_news_ids: string[];
  verdict: Verdict;
  confidence: Confidence;
}

export interface ScanRow {
  ticker: string;
  price: number | null;
  pct_1d: number | null;
  pct_5d: number | null;
  volume: number | null;
  avg_volume_20d: number | null;
  rel_volume: number | null;
  rsi_14: number | null;
  macd_hist: number | null;
  macd_cross: 'bullish' | 'bearish' | null;
  flags: string[];
  news_count?: number;
  tier?: 'mega' | 'large' | 'midsmall';
  membership?: string[];
  synthesis?: Synthesis;
}

export interface ScanData {
  generated_at: string;
  window: Window;
  universe_size: number;
  row_count: number;
  synthesized_count: number;
  rows: ScanRow[];
}

export interface RankJump {
  ticker: string;
  from: number;
  to: number;
  delta: number;
}

export interface DeltaData {
  generated_at: string;
  prior_scan_at: string | null;
  new_top20_entrants: string[];
  rank_jumps: RankJump[];
  momentum_accel: string[];
}

export interface NewsItem {
  id: string;
  source: string;
  publisher: string;
  ticker: string | null;
  scope: 'ticker' | 'macro';
  title: string;
  url: string;
  published_at: string;
  type?: string;
  impact?: Impact;
  dedup_group?: string;
  tickers_mentioned?: string[];
  route_to_synthesis?: boolean;
}

export interface BeneficiaryEntry {
  ticker: string;
  rationale: string;
  confidence: Confidence;
  horizon: Horizon;
}

export interface MacroEvent {
  event_summary: string;
  primary_drivers: string[];
  beneficiaries: BeneficiaryEntry[];
  losers: BeneficiaryEntry[];
  dedup_group: string;
  source_news_ids: string[];
  headlines: string[];
}

export interface NewsData {
  generated_at: string;
  ticker_news: Record<string, NewsItem[]>;
  macro_events: MacroEvent[];
}

export interface Watchlist {
  tickers: string[];
}
