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
  sector?: string;
  spark?: number[];
  caution_level?: 'caution' | 'stretched';
  caution_reasons?: string[];
  snapshot?: {
    live_price: number | null;
    prev_close: number | null;
    gap_pct: number | null;
  };
  intraday?: {
    vwap: number | null;
    hod: number;
    lod: number;
    last: number;
    above_vwap: boolean | null;
    bars: number;
  };
  synthesis?: Synthesis;
}

// Market regime snapshot from scanner/regime.py compute(). Fails soft to {}
// upstream, so every field is optional; `label` is the one to render.
export interface Regime {
  label?: 'risk_on' | 'risk_off' | 'mixed';
  [key: string]: unknown;
}

export interface ScanData {
  generated_at: string;
  window: Window;
  universe_size: number;
  row_count: number;
  synthesized_count: number;
  recommendations?: Recommendations;
  regime?: Regime;
  rows: ScanRow[];
}

export type RecDirection = 'long' | 'short';

// "long" = catalyst-backed (synthesis says news explains the move) — a thesis
// to hold beyond the next tick. "short" = pure technical / price-action trade.
export type RecHorizon = 'long' | 'short';

// Tier-4 agent-desk verdict attached to a pick. Keep in sync with
// scanner/desk/__init__.py review(). All fields nullable — the desk fails soft.
export type DeskVote = 'agree' | 'neutral' | 'against';
export interface DeskAdvisorVote {
  vote: DeskVote;
  conviction: number;
  note: string;
}
export interface DeskRiskVote {
  veto: boolean;
  severity: 'low' | 'medium' | 'high';
  concern: string;
}
export interface DeskVerdict {
  decision: 'take' | 'pass' | null;
  size: 'full' | 'half' | 'quarter' | 'none' | null;
  agreement: 'unanimous' | 'majority' | 'split' | 'pm_override' | null;
  rationale: string | null;
  /** PM's plain-language trade plan (2-4 sentences). */
  plan?: string | null;
  signal?: DeskAdvisorVote | null;
  research?: DeskAdvisorVote | null;
  risk?: DeskRiskVote | null;
}

// Heuristic trade levels. Computed server-side (scanner/levels.py) and attached
// as rec.levels; the frontend lib/levels.ts can also compute the same shape
// client-side as a fallback before the scanner populates it.
export interface TradeLevels {
  side: 'long' | 'short';
  entry: number;
  pivot: number;
  pivotLabel: 'support' | 'resistance';
  stop: number;
  target: number;
  rr: number | null;
}

// A pick from the backend scanner.recommend module, joined to its ScanRow by
// ticker for display. Keep in sync with scanner/recommend.py compute().
export interface Recommendation {
  ticker: string;
  direction: RecDirection;
  horizon: RecHorizon;
  score: number;
  reasons: string[];
  cautions: string[];
  desk?: DeskVerdict | null;
  levels?: TradeLevels | null;
}

export interface Recommendations {
  longs: Recommendation[];
  shorts: Recommendation[];
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

// predictions.json — the ripple tier's forward second-order calls. Keep in sync
// with scanner/llm/ripple.py + scanner/render.write_predictions().
export type PredictionDirection = 'bullish' | 'bearish';
// Where the live tape sits vs. the prediction. 'no' = hasn't moved our way yet
// (the actionable "before" call we push); 'contradicted' = moved hard against.
export type PricedIn = 'no' | 'partial' | 'yes' | 'contradicted';

export interface RipplePrediction {
  ticker: string;
  direction: PredictionDirection;
  rationale: string;
  confidence: Confidence;
  horizon: Horizon;
  priced_in: PricedIn;
  pct_1d: number | null;
  rel_volume: number | null;
  trigger_ticker: string;
  event_summary: string;
  news_url: string | null;
  source_news_ids: string[];
  /** When the call was first made — survives re-emission across scans. */
  created_at?: string;
}

export interface RippleEvent {
  event_summary: string;
  primary_drivers: string[];
  beneficiaries: BeneficiaryEntry[];
  losers: BeneficiaryEntry[];
  trigger_ticker: string;
  source_news_ids: string[];
  headlines: string[];
  news_url: string | null;
}

export interface PredictionsData {
  generated_at: string;
  event_count: number;
  prediction_count: number;
  not_yet_priced_in: number;
  events: RippleEvent[];
  predictions: RipplePrediction[];
}

// prediction_performance.json — keep in sync with
// scanner/performance.compile_prediction_stats(). Two groupings: does the
// model's confidence mean anything, and do the not-yet-moved calls actually pay?
export interface PredictionPerformance {
  generated_at: string;
  window_days: number;
  total_predictions: number;
  by_confidence: Record<string, AlertTypeStats>;
  by_priced_in: Record<string, AlertTypeStats>;
  /** Calls pushed without a scan-row entry price — visible, not hidden. */
  untracked_count?: number;
  horizon_note?: string;
}

export interface Watchlist {
  tickers: string[];
}

export type WeeklyClassification = 'real_momentum' | 'fakeout' | 'unclear';
export type WeeklyPrediction = 'continuation' | 'reversal' | 'rangebound';

export interface WeeklyAnalysis {
  classification: WeeklyClassification;
  classification_reasoning: string;
  prediction: WeeklyPrediction;
  prediction_confidence: Confidence;
  prediction_rationale: string;
  support_level?: number;
  resistance_level?: number;
  catalysts_ahead?: string[];
  horizon_days?: number;
}

export interface WeeklyMetrics {
  week_return_pct: number;
  week_high: number;
  week_low: number;
  week_close: number;
  retention_of_peak: number;
  vol_persistence: number;
  event_count: number;
  news_density: number;
}

export interface WeeklyTickerEntry {
  ticker: string;
  event_count: number;
  heuristic_classification: WeeklyClassification;
  metrics: WeeklyMetrics;
  analysis: WeeklyAnalysis | null;
}

export interface WeeklyData {
  generated_at: string;
  week_ending: string;
  ticker_count: number;
  analyses: WeeklyTickerEntry[];
}

export interface HorizonStats {
  evaluated: number;
  hit_rate: number | null;
  avg_return_pct: number | null;
  /** Net of the 0.5% round-trip slippage drag (perf-roadmap). */
  hit_rate_net?: number | null;
  avg_return_net_pct?: number | null;
}

export interface AlertTypeStats {
  count: number;
  horizons: {
    '1d'?: HorizonStats;
    '3d'?: HorizonStats;
    '5d'?: HorizonStats;
  };
}

export interface PerformanceData {
  generated_at: string;
  window_days: number;
  total_alerts: number;
  per_type: Record<string, AlertTypeStats>;
}

// recommendation_performance.json — keep in sync with
// scanner/performance.compile_recommendation_stats(). per_bucket is keyed
// "<direction>_<band>", e.g. "long_hi", "short_lo".
export interface RecommendationPerformance {
  generated_at: string;
  window_days: number;
  total_picks: number;
  high_score: number;
  per_bucket: Record<string, AlertTypeStats>;
}

// desk_performance.json — keep in sync with scanner/performance.compile_desk_stats().
// Validates whether the agent desk's take/pass calls separate winners from losers.
export interface DeskPerformance {
  generated_at: string;
  window_days: number;
  total_with_desk: number;
  by_decision: Record<string, AlertTypeStats>;
  by_agreement: Record<string, AlertTypeStats>;
  by_veto: Record<string, AlertTypeStats>;
  take_minus_pass_edge: Record<string, number | null>;
}

// political.json — keep in sync with scanner/political._normalize().
// Disclosed Congressional stock trades, fetched daily from FMP.
export type PoliticalChamber = 'senate' | 'house';
export type PoliticalSide = 'buy' | 'sell' | 'exchange' | 'unknown' | string;

export interface PoliticalTrade {
  chamber: PoliticalChamber;
  politician: string | null;
  ticker: string | null;
  side: PoliticalSide;
  amount_band: string | null;
  transaction_date: string | null;
  filed_at: string | null;
  owner: string | null;
  asset_description: string | null;
  link: string | null;
}

export interface PoliticalData {
  generated_at: string;
  status: 'ok' | 'empty' | 'no_key' | 'djt_only' | string;
  source?: string;
  window_days: number;
  total_trades: number;
  unique_tickers: number;
  trades: PoliticalTrade[];
  by_ticker: Record<string, PoliticalTrade[]>;
  djt?: DjtInsiderData | null;
}

// SEC Form 4 transaction codes most relevant here:
// P = open-market purchase, S = open-market sale, A = grant/award,
// M = option exercise, F = tax withholding, G = gift.
export interface DjtTransaction {
  filed_at: string;
  accession: string;
  owner: string | null;
  is_trump_family: boolean;
  transaction_date: string | null;
  code: string | null;
  code_label: string | null;
  acquired_disposed: 'A' | 'D' | string | null;
  shares: number | null;
  price: number | null;
  link: string;
}

export interface DjtInsiderData {
  issuer: string;
  tickers: string[];
  trust_status: {
    trust_name: string;
    trust_cik: string;
    holding_shares_known: number;
    holding_as_of: string;
    trump_family_filings_in_last_scan: number;
    form4s_scanned: number;
    note: string;
  };
  recent_transactions: DjtTransaction[];
}

// trump_pulse.json — keep in sync with scanner/trump_pulse.fetch_and_save().
export interface TruthPost {
  ts: string | null;
  text: string;
  url: string | null;
  ticker_mentions: string[];
  source?: 'truth_social' | 'news';
}
export interface PresidentialDocument {
  title: string;
  type: string;
  signing_date: string | null;
  publication_date: string | null;
  document_number: string | null;
  html_url: string | null;
  abstract: string | null;
}
export interface MentionDetail {
  count: number;
  last_ts: string | null;
  last_excerpt: string | null;
  last_url: string | null;
}
export interface TrumpPulseData {
  generated_at: string;
  sources: Record<string, string>;
  window_days?: number;
  truth_post_count: number;
  news_post_count?: number;
  document_count: number;
  tickers_mentioned: string[];
  mention_summary?: Record<string, MentionDetail>;
  truth_posts: TruthPost[];
  news_posts?: TruthPost[];
  presidential_documents: PresidentialDocument[];
}

// trump_basket.json — hand-curated thematic basket. NOT advice; see _comment.
export interface TrumpBasketTheme {
  name: string;
  note?: string;
  tickers: string[];
}
export interface TrumpBasket {
  _comment?: string;
  themes: TrumpBasketTheme[];
}

// serenity.json — keep in sync with scanner/serenity.py (the 24/7 X poller).
// English-only on this side; the live-scan cross-reference (which named tickers
// are moving) is computed client-side from scan.json on the /serenity page.
export type SerenityStance = 'bull' | 'bear' | 'neutral';

export interface SerenityTweet {
  id: string;
  url: string;
  createdAt: string;
  text: string;
  isReply: boolean;
  isQuote: boolean;
  metrics?: { likes: number; reposts: number; replies: number; views?: number };
  tickers: string[];
  stance: SerenityStance;
  summaryEn: string;
}

export interface SerenityData {
  generated_at: string;
  tweets: SerenityTweet[];
}

// ledger.json — the committed accountability ledger: every dispatched alert,
// pick, and prediction with its outcome. Keep in sync with the ledger writer
// in scanner/performance.py.
export type LedgerStatus = 'pending' | 'hit' | 'miss' | 'untracked';

export interface LedgerEntry {
  id: string;
  ts: string;
  kind: 'alert' | 'pick' | 'prediction';
  type: string;
  ticker: string;
  direction: 'long' | 'short' | null;
  confidence: string | null;
  price: number | null;
  thesis: string;
  outcomes: { '1d': number | null; '3d': number | null; '5d': number | null };
  status: LedgerStatus;
}

export interface LedgerData {
  generated_at: string;
  window_days: number;
  entries: LedgerEntry[];
}

// briefing.json — one structured LLM call per scan; the answer-first top of
// the home page. Keep in sync with scanner/briefing.py.
export interface BriefingAction {
  ticker: string;
  direction: 'long' | 'short';
  entry: number | null;
  stop: number | null;
  target: number | null;
  line: string;
}

export interface BriefingWatch {
  ticker: string;
  type: string;
  line: string;
}

export interface BriefingData {
  generated_at: string;
  window: string;
  headline: string;
  market_state: { regime: string; line: string };
  actions: BriefingAction[];
  watch: BriefingWatch[];
  changed: string[];
  caveats: string[];
}

// --- Deal flow (/deals): ripple events surfaced as deals, each with its
// second-order prediction chain and the grades those calls earned. ---
export interface DealPrediction {
  ticker: string;
  direction: 'long' | 'short';
  mechanism: string;
  confidence: Confidence;
  horizon: Horizon;
  priced_in: PricedIn;
  outcomes: { '1d': number | null; '3d': number | null; '5d': number | null };
  status: 'pending' | 'hit' | 'miss';
}

export interface Deal {
  id: string;
  ts: string;
  primary_ticker: string;
  counterparty: string | null;
  headline: string;
  drivers: string[];
  news_url: string | null;
  predictions: DealPrediction[];
  stats: { calls: number; graded: number; hit: number };
}

export interface DealsData {
  generated_at: string;
  window_days: number;
  deal_count: number;
  deals: Deal[];
}

// --- Catalyst calendar (/catalysts): portfolio-driven forward event calendar.
// Keep in sync with scanner/catalysts.py + scanner/llm/catalyst_notes.py. ---
export type CatalystType = 'earnings' | 'ex_dividend' | 'macro' | 'witching';
// Forward earnings from FMP are aggregator estimates; dividends/macro/witching
// are scheduled or declared. The badge makes that distinction visible.
export type CatalystConfidence = 'confirmed' | 'estimated';

export interface CatalystEvent {
  id: string;
  ticker?: string; // absent on macro/witching events
  type: CatalystType;
  label: string;
  date: string; // YYYY-MM-DD
  days_until: number;
  impact: Impact;
  confidence: CatalystConfidence;
  detail?: string;
  source: string;
}

export type CatalystStance =
  | 'add-on-weakness'
  | 'trim-into-strength'
  | 'hold'
  | 'watch'
  | 'reduce-risk';

export interface CatalystNote {
  stance: CatalystStance;
  read: string;
  next_catalyst: string;
  bull: string;
  bear: string;
  confidence: Confidence;
}

export interface PortfolioHolding {
  ticker: string;
  shares?: number | null;
  cost_basis?: number | null;
  note?: string | null;
}

export interface CatalystsData {
  generated_at: string;
  status: 'ok' | 'no_key' | 'no_portfolio' | string;
  source?: string;
  horizon_days: number;
  portfolio_count: number;
  holdings: PortfolioHolding[];
  catalyst_count: number;
  by_ticker: Record<string, CatalystEvent[]>;
  macro: CatalystEvent[];
  notes_by_ticker: Record<string, CatalystNote>;
  notes_generated_at?: string | null;
  disclaimer?: string;
}
