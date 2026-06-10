// Ask-the-tape: one serverless function that answers free-form questions over
// the site's committed JSON (scan, news, ledger, weekly, serenity, predictions,
// performance). The data is batch — every answer leads with its age.
//
// Auth: single-user bearer via the x-ask-token header matched against the
// ASK_TOKEN env var. Unset ASK_TOKEN (or ANTHROPIC_API_KEY) → 503, so a
// deploy without secrets is inert rather than an open LLM endpoint.
import { json } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';
import Anthropic from '@anthropic-ai/sdk';
import type { RequestHandler } from './$types';
import type {
  ScanData,
  NewsData,
  WeeklyData,
  SerenityData,
  PredictionsData,
  PerformanceData,
  LedgerData,
  BriefingData
} from '$lib/types';

// Vercel hobby caps default function duration well below a worst-case LLM
// call; raise it for this route only.
export const config = { maxDuration: 60 };

const MAX_QUESTION_CHARS = 400;
const MAX_TICKERS = 3;

// Tickers that are also common English words — only match these when the
// asker wrote them in ALL CAPS or with a $ prefix.
const AMBIGUOUS = new Set([
  'A', 'AN', 'ALL', 'ARE', 'BE', 'BY', 'CAN', 'FOR', 'GO', 'HAS', 'IT', 'NEXT',
  'NICE', 'NOW', 'ON', 'ONE', 'OPEN', 'OR', 'OUT', 'PLAY', 'REAL', 'SO', 'SEE',
  'BIG', 'GOOD', 'WELL', 'CASH', 'FAST', 'EVER', 'FUN', 'HUGE', 'LOVE', 'MAIN',
  'NEW', 'PEAK', 'SAFE', 'TELL', 'TRUE', 'TURN', 'VERY', 'WHO', 'WHY', 'YOU'
]);

const SYSTEM_PROMPT = `You are the Momentum desk assistant — the question-answering layer of a personal momentum scanner (scan data, news, a 24/7 X feed called Serenity, ripple predictions, a call ledger with outcomes).

Hard rules:
- ALWAYS open your answer with the data age in one short clause (compute it from DATA.meta.generated_at vs NOW), e.g. "Scan is 2.5h old (AH_POST) —". The data is batch JSON committed every ~2-3h, NOT live. If asked about "right now" prices, say plainly that you only have the scan snapshot.
- Use ONLY tickers, prices, and numbers present in DATA. Never invent or estimate a quote. If the data doesn't cover the question, say what's missing in one line.
- Answer in the language the question was asked in (Chinese question → Chinese answer).
- Terse trader voice: lead with the read, then the evidence. Numbers inline, no tables, no headers, usually under 120 words. No hedging boilerplate, but be honest about uncertainty.
- When DATA.signal_trust shows a signal class is historically noise (e.g. serenity_match), weigh and mention that when the question touches it.
- You give reads on the tape, not financial advice; frame entries/stops as "the plan on file" or "what the levels say", never as instructions to buy.`;

type Fetch = typeof fetch;

async function load<T>(fetch: Fetch, path: string): Promise<T | null> {
  try {
    const r = await fetch(`/data/${path}`);
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

function detectTickers(question: string, known: Set<string>): string[] {
  const found: string[] = [];
  const seen = new Set<string>();
  for (const m of question.matchAll(/\$?([A-Za-z]{1,5})\b/g)) {
    const raw = m[1];
    const upper = raw.toUpperCase();
    if (seen.has(upper) || !known.has(upper)) continue;
    const explicit = m[0].startsWith('$') || raw === upper;
    if (AMBIGUOUS.has(upper) && !explicit) continue;
    if (upper.length === 1 && !m[0].startsWith('$')) continue;
    seen.add(upper);
    found.push(upper);
    if (found.length >= MAX_TICKERS) break;
  }
  return found;
}

function trim(s: string | null | undefined, n: number): string | undefined {
  if (!s) return undefined;
  return s.length > n ? s.slice(0, n) + '…' : s;
}

export const POST: RequestHandler = async ({ request, fetch }) => {
  if (!env.ASK_TOKEN || !env.ANTHROPIC_API_KEY) {
    return json(
      { error: 'not configured', detail: 'ASK_TOKEN and ANTHROPIC_API_KEY must be set in the deployment env' },
      { status: 503 }
    );
  }
  if (request.headers.get('x-ask-token') !== env.ASK_TOKEN) {
    return json({ error: 'unauthorized' }, { status: 401 });
  }

  let question: string;
  try {
    const body = await request.json();
    question = String(body?.question ?? '').trim();
  } catch {
    return json({ error: 'bad request' }, { status: 400 });
  }
  if (!question) return json({ error: 'empty question' }, { status: 400 });
  if (question.length > MAX_QUESTION_CHARS) {
    return json({ error: `question too long (max ${MAX_QUESTION_CHARS} chars)` }, { status: 400 });
  }

  const [scan, news, weekly, serenity, predictions, performance, ledger, briefing] =
    await Promise.all([
      load<ScanData>(fetch, 'scan.json'),
      load<NewsData>(fetch, 'news.json'),
      load<WeeklyData>(fetch, 'weekly.json'),
      load<SerenityData>(fetch, 'serenity.json'),
      load<PredictionsData>(fetch, 'predictions.json'),
      load<PerformanceData>(fetch, 'performance.json'),
      load<LedgerData>(fetch, 'ledger.json'),
      load<BriefingData>(fetch, 'briefing.json')
    ]);

  if (!scan) return json({ error: 'scan data unavailable' }, { status: 502 });

  const rowsByTicker = new Map(scan.rows.map((r) => [r.ticker, r]));
  const known = new Set(rowsByTicker.keys());
  // The scan only carries moving names; weekly/ledger/serenity history can
  // answer questions about anything we've ever covered.
  for (const e of weekly?.analyses ?? []) known.add(e.ticker);
  for (const e of ledger?.entries ?? []) known.add(e.ticker);
  for (const p of predictions?.predictions ?? []) known.add(p.ticker);
  const tickers = detectTickers(question, known);

  const top10 = [...scan.rows]
    .filter((r) => r.pct_1d != null)
    .sort((a, b) => Math.abs(b.pct_1d!) - Math.abs(a.pct_1d!))
    .slice(0, 10)
    .map((r) => `${r.ticker} ${r.pct_1d! > 0 ? '+' : ''}${r.pct_1d!.toFixed(1)}% rvol ${r.rel_volume?.toFixed(1) ?? '–'}x`);

  const recs = scan.recommendations;
  const takes = [...(recs?.longs ?? []), ...(recs?.shorts ?? [])]
    .filter((r) => !r.desk || r.desk.decision === 'take')
    .map((r) => ({
      ticker: r.ticker,
      direction: r.direction,
      score: r.score,
      size: r.desk?.size,
      levels: r.levels ? { entry: r.levels.entry, stop: r.levels.stop, target: r.levels.target } : undefined,
      plan: trim(r.desk?.plan, 240)
    }));

  const perTicker = tickers.map((t) => {
    const row = rowsByTicker.get(t);
    const tickerNews = (news?.ticker_news?.[t] ?? []).slice(0, 5).map((n) => ({
      title: n.title,
      published_at: n.published_at,
      impact: n.impact
    }));
    const serenityMentions = (serenity?.tweets ?? [])
      .filter((tw) => tw.tickers.includes(t))
      .slice(0, 3)
      .map((tw) => ({ at: tw.createdAt, stance: tw.stance, summary: tw.summaryEn || trim(tw.text, 160) }));
    const weeklyEntry = weekly?.analyses?.find((e) => e.ticker === t);
    const ledgerEntries = (ledger?.entries ?? [])
      .filter((e) => e.ticker === t)
      .slice(0, 8)
      .map((e) => ({ ts: e.ts, type: e.type, direction: e.direction, outcomes: e.outcomes, status: e.status }));
    const predsAbout = (predictions?.predictions ?? [])
      .filter((p) => p.ticker === t || p.trigger_ticker === t)
      .slice(0, 4)
      .map((p) => ({
        ticker: p.ticker,
        via: p.trigger_ticker,
        direction: p.direction,
        confidence: p.confidence,
        horizon: p.horizon,
        priced_in: p.priced_in,
        created_at: p.created_at,
        rationale: trim(p.rationale, 200)
      }));
    return {
      ticker: t,
      scan_row: row
        ? {
            price: row.price,
            pct_1d: row.pct_1d,
            pct_5d: row.pct_5d,
            rel_volume: row.rel_volume,
            rsi_14: row.rsi_14,
            macd_hist: row.macd_hist,
            flags: row.flags,
            sector: row.sector,
            tier: row.tier,
            gap_pct: row.snapshot?.gap_pct,
            vwap: row.intraday?.vwap,
            above_vwap: row.intraday?.above_vwap,
            synthesis: row.synthesis ? { verdict: row.synthesis.verdict, summary: trim(row.synthesis.summary, 280) } : undefined
          }
        : 'not in current scan',
      news: tickerNews.length ? tickerNews : undefined,
      serenity: serenityMentions.length ? serenityMentions : undefined,
      weekly: weeklyEntry?.analysis
        ? {
            week_ending: weekly?.week_ending,
            classification: weeklyEntry.analysis.classification,
            prediction: weeklyEntry.analysis.prediction,
            confidence: weeklyEntry.analysis.prediction_confidence,
            reasoning: trim(weeklyEntry.analysis.classification_reasoning, 320)
          }
        : undefined,
      past_calls: ledgerEntries.length ? ledgerEntries : undefined,
      predictions: predsAbout.length ? predsAbout : undefined
    };
  });

  const signalTrust = Object.fromEntries(
    Object.entries(performance?.per_type ?? {}).map(([k, v]) => {
      const h = v.horizons?.['1d'];
      return [k, h ? `${Math.round((h.hit_rate ?? 0) * 100)}% 1d hit, ${h.avg_return_pct ?? '–'}% avg, n=${h.evaluated}` : 'no outcomes'];
    })
  );

  const data = {
    meta: {
      generated_at: scan.generated_at,
      window: scan.window,
      regime: scan.regime?.label ?? 'unknown',
      scanned: scan.row_count
    },
    briefing: briefing ? { generated_at: briefing.generated_at, headline: briefing.headline, market: briefing.market_state?.line } : undefined,
    top_movers: top10,
    desk_takes: takes,
    signal_trust: signalTrust,
    tickers: perTicker.length ? perTicker : undefined
  };

  const client = new Anthropic({ apiKey: env.ANTHROPIC_API_KEY, timeout: 50_000, maxRetries: 1 });
  const model = env.ASK_MODEL || 'claude-sonnet-4-6';

  try {
    const response = await client.messages.create({
      model,
      max_tokens: 1200,
      output_config: { effort: 'medium' },
      system: SYSTEM_PROMPT,
      messages: [
        {
          role: 'user',
          content: `NOW: ${new Date().toISOString()}\n\nDATA:\n${JSON.stringify(data)}\n\nQUESTION: ${question}`
        }
      ]
    });
    const answer = response.content
      .filter((b) => b.type === 'text')
      .map((b) => (b as { type: 'text'; text: string }).text)
      .join('\n')
      .trim();
    if (!answer) return json({ error: 'empty answer from model' }, { status: 502 });
    const ageMin = Math.round((Date.now() - new Date(scan.generated_at).getTime()) / 60_000);
    return json({ answer, model: response.model, data_age_minutes: ageMin, tickers });
  } catch (e) {
    if (e instanceof Anthropic.RateLimitError) {
      return json({ error: 'rate limited — try again in a minute' }, { status: 429 });
    }
    if (e instanceof Anthropic.AuthenticationError) {
      return json({ error: 'ANTHROPIC_API_KEY invalid' }, { status: 502 });
    }
    if (e instanceof Anthropic.APIError) {
      return json({ error: `model call failed (${e.status})` }, { status: 502 });
    }
    return json({ error: 'model call failed' }, { status: 502 });
  }
};
