// Live indicator interpretations. The ticker page already shows the raw numbers
// (VWAP $12.34, RSI 61, RVOL 2.8×); this turns each one into a plain-language
// "what it means" read so a learner doesn't have to cross-reference /learn.
// Same colour coding as the guide: green = bullish, red = bearish, amber =
// caution, gray = neutral.
//
// Every read returns null when its source datum is missing — VWAP / Gap / day
// position only exist during a live session, RSI / MACD / RVOL / volatility are
// always present from the daily bars — so the caller renders whatever it has.

import type { ScanRow } from './types';

export type ReadTone = 'up' | 'down' | 'warn' | 'flat';

export interface IndicatorRead {
  key: string;
  name: string; // universal indicator name — matches the /learn guide
  value: string; // the live number, formatted
  verdict: string; // plain-language read (Chinese-primary, matches the guide's voice)
  tone: ReadTone;
}

const f2 = (n: number) => n.toFixed(2);

function vwapRead(row: ScanRow): IndicatorRead | null {
  const iv = row.intraday;
  if (!iv || iv.above_vwap == null || iv.vwap == null) return null;
  return iv.above_vwap
    ? {
        key: 'vwap',
        name: 'VWAP',
        value: `$${f2(iv.vwap)}`,
        tone: 'up',
        verdict: '↑ 价在 VWAP 上方 · 多头掌控,回踩 VWAP 常是买点'
      }
    : {
        key: 'vwap',
        name: 'VWAP',
        value: `$${f2(iv.vwap)}`,
        tone: 'down',
        verdict: '↓ 价在 VWAP 下方 · 空头掌控,反弹易被卖,别追多'
      };
}

function rangeRead(row: ScanRow): IndicatorRead | null {
  const iv = row.intraday;
  if (!iv || iv.hod == null || iv.lod == null || iv.last == null) return null;
  const span = iv.hod - iv.lod;
  if (span <= 0) return null;
  const pos = Math.round(((iv.last - iv.lod) / span) * 100);
  const value = `${pos}%`;
  if (pos >= 80)
    return { key: 'range', name: '日内位置', value, tone: 'up', verdict: '贴近当日高点 · 强势,买方占优' };
  if (pos <= 20)
    return { key: 'range', name: '日内位置', value, tone: 'down', verdict: '贴近当日低点 · 弱势,卖方占优' };
  return { key: 'range', name: '日内位置', value, tone: 'flat', verdict: '日内区间中部 · 多空胶着' };
}

function rvolRead(row: ScanRow): IndicatorRead | null {
  const rv = row.rel_volume;
  if (rv == null) return null;
  const value = `${rv.toFixed(1)}×`;
  if (rv >= 2)
    return { key: 'rvol', name: 'RVOL', value, tone: 'up', verdict: '异常放量 · 有真实买盘/燃料,move 更可信' };
  if (rv >= 1)
    return { key: 'rvol', name: 'RVOL', value, tone: 'flat', verdict: '量能正常 · 没有特别关注' };
  return { key: 'rvol', name: 'RVOL', value, tone: 'down', verdict: '缩量 · 没人理,多半是假动作,别太当真' };
}

function rsiRead(row: ScanRow): IndicatorRead | null {
  const r = row.rsi_14;
  if (r == null) return null;
  const value = r.toFixed(0);
  if (r >= 72)
    return { key: 'rsi', name: 'RSI', value, tone: 'warn', verdict: '超买 · 短期有回调风险,追高要小心' };
  if (r >= 55)
    return { key: 'rsi', name: 'RSI', value, tone: 'up', verdict: '健康趋势区 · 多头有力但不过热' };
  if (r >= 30)
    return { key: 'rsi', name: 'RSI', value, tone: 'flat', verdict: '中性偏弱 · 没有明显动能' };
  return { key: 'rsi', name: 'RSI', value, tone: 'down', verdict: '超卖 · 极度弱势,可能技术性反弹' };
}

function macdRead(row: ScanRow): IndicatorRead | null {
  const cross = row.macd_cross;
  const hist = row.macd_hist;
  const histStr = hist != null ? hist.toFixed(2) : null;
  if (cross === 'bullish')
    return { key: 'macd', name: 'MACD', value: histStr ?? '↑', tone: 'up', verdict: '金叉 · 动量刚转上,顺势信号' };
  if (cross === 'bearish')
    return { key: 'macd', name: 'MACD', value: histStr ?? '↓', tone: 'down', verdict: '死叉 · 动量刚转下,留意走弱' };
  if (hist == null) return null;
  if (hist > 0)
    return { key: 'macd', name: 'MACD', value: histStr!, tone: 'up', verdict: '柱在零轴上方 · 动量偏多' };
  if (hist < 0)
    return { key: 'macd', name: 'MACD', value: histStr!, tone: 'down', verdict: '柱在零轴下方 · 动量偏空' };
  return { key: 'macd', name: 'MACD', value: '0.00', tone: 'flat', verdict: '动量持平 · 方向不明' };
}

function gapRead(row: ScanRow): IndicatorRead | null {
  const g = row.snapshot?.gap_pct;
  if (g == null) return null;
  const value = `${g >= 0 ? '+' : ''}${g.toFixed(1)}%`;
  if (g >= 2)
    return { key: 'gap', name: 'Gap', value, tone: 'up', verdict: '高开 · 隔夜有催化,关注能否守住缺口' };
  if (g <= -2)
    return { key: 'gap', name: 'Gap', value, tone: 'down', verdict: '低开 · 隔夜有利空或获利了结' };
  return { key: 'gap', name: 'Gap', value, tone: 'flat', verdict: '基本平开 · 无隔夜跳空' };
}

function volatilityRead(row: ScanRow): IndicatorRead | null {
  const spark = row.spark;
  if (!spark || spark.length < 5 || row.price == null || row.price <= 0) return null;
  // Mean absolute close-to-close move — a simple ATR%-style volatility proxy,
  // the same one levels.ts uses to size stops.
  let sum = 0;
  let n = 0;
  for (let i = 1; i < spark.length; i++) {
    const prev = spark[i - 1];
    if (prev > 0) {
      sum += Math.abs(spark[i] / prev - 1);
      n++;
    }
  }
  if (!n) return null;
  const atrPct = (sum / n) * 100;
  return {
    key: 'atr',
    name: '波动 ATR',
    value: `~${atrPct.toFixed(1)}%/日`,
    tone: 'flat',
    verdict: '止损至少放 1.5–2× 这个幅度之外,才不会被日常噪音洗出'
  };
}

// Reading order: direction first (who's in control), then strength, then
// momentum, then risk — the order a trader actually checks a chart.
export function readsFor(row: ScanRow): IndicatorRead[] {
  return [
    vwapRead(row),
    rangeRead(row),
    rvolRead(row),
    rsiRead(row),
    macdRead(row),
    gapRead(row),
    volatilityRead(row)
  ].filter((r): r is IndicatorRead => r !== null);
}
