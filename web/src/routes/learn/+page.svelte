<script lang="ts">
  // Indicator guide — a bilingual cheat-sheet so a learner can decode any
  // signal they see on a ticker. Faithful to the reference card, with an
  // honest "is this live on our site" tag per indicator.

  type Side = { head: string; body: string };
  type Note = { tone: 'up' | 'down' | 'warn' | 'flat'; text: string };
  type Status = 'live' | 'partial' | 'soon';
  type Indicator = {
    name: string;
    sub: string;
    bull?: Side;
    bear?: Side;
    notes?: Note[];
    tip?: string;
    status: Status;
    where: string;
  };
  type Group = { zh: string; en: string; tagline: string; items: Indicator[] };

  const groups: Group[] = [
    {
      zh: '方向型',
      en: 'DIRECTIONAL',
      tagline: '谁说了算 / who is in control',
      items: [
        {
          name: 'VWAP',
          sub: '成交量加权均价 · 机构公平价基准',
          bull: { head: '↑ 在上', body: '多头掌控 · 回踩 VWAP 是买点' },
          bear: { head: '↓ 在下', body: '空头掌控 · 反弹被卖 · 别做多' },
          tip: '收复 = 转强 · 跌破 = 转弱(穿越那刻信息量最大)',
          status: 'live',
          where: '推荐卡 / ticker 显示 >VWAP·<VWAP,筛选器有 VWAP Above'
        },
        {
          name: '均线 9 / 20 EMA',
          sub: '趋势骨架 · trend skeleton',
          bull: { head: '↑ 站上 9/20', body: '短期趋势在 · 顺势持有' },
          bear: { head: '↓ 跌破', body: '破 9 = 裂缝 · 破 20 = 第一警报' },
          tip: '50 SMA 跌破 = 中期走坏,波段客离场区',
          status: 'soon',
          where: '暂用 MACD 代替(它内部也是 EMA);独立的 9/20 判断待接入'
        },
        {
          name: '关键价位 Key Levels',
          sub: '前日高低 PDH/PDL · 盘前高低',
          bull: { head: '↑ 突破上方', body: '新买盘进 · 上方真空 · 动量进场' },
          bear: { head: '↓ 跌破下方', body: '破位 · 卖方占优 · 离场/做空触发' },
          tip: '价位会翻转:突破后阻力变支撑',
          status: 'partial',
          where: '已有 gap%、当日高低 HOD/LOD、推荐卡 support/target;PDH/PDL 待补'
        }
      ]
    },
    {
      zh: '强度型',
      en: 'MAGNITUDE',
      tagline: '真不真 + 赔多少 / is it real + risk',
      items: [
        {
          name: 'RVOL 相对成交量',
          sub: '当前量 vs 同时段均量',
          notes: [
            { tone: 'up', text: '> 2–3x 异常关注 · 有燃料 · 可交易' },
            { tone: 'down', text: '< 1x 没人理 · 多半假动作' }
          ],
          status: 'live',
          where: '推荐卡/行显示 vol 2.8x,筛选器有 ≥2× avg'
        },
        {
          name: 'Float 流通盘',
          sub: '真正能交易的股数',
          notes: [
            { tone: 'warn', text: '低 float 爆发力强 · 但反向也暴力' },
            { tone: 'flat', text: '高 float 笨重 · 要大量才推得动' }
          ],
          status: 'soon',
          where: '需接入数据源(FMP 免费有 shares-float)'
        },
        {
          name: 'ATR 平均波幅',
          sub: '定止损 + 定仓位(非方向)',
          notes: [
            { tone: 'flat', text: '止损放 1.5–2x ATR 之外 → 不被噪音洗出' },
            { tone: 'flat', text: 'ATR 大 → 波动大 → 仓位调小' }
          ],
          status: 'partial',
          where: '推荐卡的止损已用 ATR 估算;数值本身暂未单独显示'
        }
      ]
    },
    {
      zh: '本站其它指标',
      en: 'ALSO LIVE HERE',
      tagline: '推荐卡上你还会看到 / other signals on the cards',
      items: [
        {
          name: 'RSI 相对强弱',
          sub: '0–100 · 超买超卖',
          notes: [
            { tone: 'up', text: '55–72 健康趋势区' },
            { tone: 'warn', text: '> 75 超买 · 短期回调风险' },
            { tone: 'down', text: '< 30 超卖 · 可能反弹' }
          ],
          status: 'live',
          where: 'ticker 显示 RSI 数值;打分用它防追高'
        },
        {
          name: 'MACD 动量交叉',
          sub: '快慢线交叉 · momentum turn',
          notes: [
            { tone: 'up', text: '金叉 bullish cross = 动量转上' },
            { tone: 'down', text: '死叉 bearish cross = 动量转下' }
          ],
          status: 'live',
          where: '推荐卡显示 MACD↑ / MACD↓ chip'
        },
        {
          name: 'Gap 跳空',
          sub: '今开 vs 昨收',
          notes: [
            { tone: 'up', text: '高开 = 隔夜有催化' },
            { tone: 'flat', text: 'gap 大 + 量大 = Gap & Go 经典开盘play' }
          ],
          status: 'live',
          where: 'ticker 显示 gap%;有 Gap & Go 预设'
        }
      ]
    }
  ];

  const STATUS: Record<Status, { label: string; cls: string }> = {
    live: { label: '✓ 已接入', cls: 'text-signal-up bg-signal-up/10' },
    partial: { label: '⚠ 部分', cls: 'text-signal-warn bg-signal-warn/10' },
    soon: { label: '○ 待接入', cls: 'text-zinc-500 bg-ink-700/60' }
  };
  const noteCls: Record<Note['tone'], string> = {
    up: 'text-signal-up',
    down: 'text-signal-down',
    warn: 'text-signal-warn',
    flat: 'text-zinc-400'
  };
</script>

<svelte:head><title>Momentum — 指标解读 / Learn</title></svelte:head>

<header class="mb-6">
  <h1 class="text-lg font-semibold tracking-tight">指标解读 · Indicator Guide</h1>
  <p class="mt-1 text-xs leading-relaxed text-zinc-500">
    看到推荐卡上的指标不懂?这里查。绿色 = 偏多,红色 = 偏空。每个指标都标了本站是否已接入。
    <span class="text-zinc-600">— Not sure what a signal means? Look it up. Green = bullish read, red = bearish.</span>
  </p>
</header>

<div class="space-y-8">
  {#each groups as g (g.en)}
    <section>
      <div class="mb-3 flex flex-wrap items-baseline gap-x-2 border-b border-ink-700 pb-2">
        <h2 class="text-base font-bold tracking-tight">{g.zh}</h2>
        <span class="text-xs font-semibold uppercase tracking-wider text-zinc-400">{g.en}</span>
        <span class="text-[11px] text-zinc-500">— {g.tagline}</span>
      </div>

      <div class="space-y-3">
        {#each g.items as ind (ind.name)}
          <div class="card p-4">
            <header class="mb-2.5 flex flex-wrap items-baseline justify-between gap-2">
              <div class="flex flex-wrap items-baseline gap-x-2">
                <h3 class="text-sm font-semibold tracking-tight">{ind.name}</h3>
                <span class="text-[11px] text-zinc-500">{ind.sub}</span>
              </div>
              <span class="rounded px-1.5 py-0.5 text-[10px] font-medium tracking-wide {STATUS[ind.status].cls}">
                {STATUS[ind.status].label}
              </span>
            </header>

            {#if ind.bull || ind.bear}
              <div class="grid gap-2 sm:grid-cols-2">
                {#if ind.bull}
                  <div class="rounded-lg border border-signal-up/20 bg-signal-up/[0.07] p-2.5">
                    <div class="text-xs font-semibold text-signal-up">{ind.bull.head}</div>
                    <div class="mt-0.5 text-xs text-zinc-300">{ind.bull.body}</div>
                  </div>
                {/if}
                {#if ind.bear}
                  <div class="rounded-lg border border-signal-down/20 bg-signal-down/[0.07] p-2.5">
                    <div class="text-xs font-semibold text-signal-down">{ind.bear.head}</div>
                    <div class="mt-0.5 text-xs text-zinc-300">{ind.bear.body}</div>
                  </div>
                {/if}
              </div>
            {/if}

            {#if ind.notes}
              <ul class="space-y-1">
                {#each ind.notes as n}
                  <li class="text-xs {noteCls[n.tone]}">{n.text}</li>
                {/each}
              </ul>
            {/if}

            {#if ind.tip}
              <p class="mt-2 text-[11px] leading-relaxed text-zinc-500">↻ {ind.tip}</p>
            {/if}
            <p class="mt-2 border-t border-ink-700/50 pt-1.5 text-[10px] leading-relaxed text-zinc-500">
              本站:{ind.where}
            </p>
          </div>
        {/each}
      </div>
    </section>
  {/each}
</div>

<p class="mt-8 text-[10px] uppercase tracking-wider text-zinc-500">
  教育用途 · 非投资建议 · Educational only, not investment advice
</p>
