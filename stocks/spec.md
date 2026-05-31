# Momentum scanner — redesign spec

Companion to `index.html`. Structured so Claude Code can lift values directly.

The four wireframes are **alternative directions**, not stages of one design. Pick one (or hybridize); the spec below covers all four.

---

## 0. Shared content model (all directions)

Every direction renders the same data — only treatment differs.

```ts
type Ticker = {
  symbol: string;              // "QUBT"
  side?: 'long' | 'short';     // picks only
  price: number;               // 12.31
  pctChange: number;           // 7.89  (signed)
  score?: number;              // 1-10, picks only
  sparkline: number[];         // 8-30 points, last N closes
  flags: TickerFlag[];         // see below
  vol?: { mult: number };      // 3.0 -> 3.0x
  rsi?: number;
  macd?: 'up' | 'down' | 'positive' | 'negative' | 'bullish-cross' | 'bearish-cross';
  marketCap?: 'mega' | 'large' | 'mid' | 'small';
  sector?: string;
  rank?: number;
};

type TickerFlag =
  | 'extended'        // † / ▲
  | 'overbought'      // ‡ / ◉
  | 'stretched'       // ⛔ in current design; ⊘ / ▼ here
  | 'new-top-20'      // § / ◆
  | 'volume-spike'    // ⚡
  | 'macd-cross'      // ↗ / ↘
  | 'watchlist'       // ★
  | 'weak'            // ↓ small
```

### Iconography map (replaces today's pill-badges)

| Flag           | Geometric | Glyph (editorial) | Color hint  |
|----------------|-----------|-------------------|-------------|
| extended       | ▲         | †                 | amber       |
| overbought     | ◉         | ‡                 | red-amber   |
| stretched      | ▼         | ⊘                 | red         |
| new-top-20     | ◆         | §                 | blue        |
| volume-spike   | ⚡        | ¶                 | amber       |
| macd up        | ↗         | ↗                 | green       |
| macd down      | ↘         | ↘                 | red         |
| watchlist      | ★         | ★                 | ink         |

Render ≤ 3 icons per row. Truncate with " +N" if more.

---

## 1. Terminal direction

**Vibe:** Bloomberg-lite. Dark, monospace, single column of % change drops the eye down the page.

### Tokens
```css
--bg:        #0e0e0e;
--bg-rule:   #1f1f1f;
--bg-divide: #2a2a2a;
--fg:        #d8d4c5;
--fg-dim:    #8a8678;
--fg-mute:   #5a5a52;
--accent:    #f6c945;  /* saffron — section headers, "on" states */
--green:     #4ade80;
--red:       #f87171;
--blue:      #6ec1ff;
--font-mono: 'JetBrains Mono', 'IBM Plex Mono', monospace;
--font-size: 13px;
--line:      1.55;
```

### Layout
- Single full-width frame, no cards
- Header row: app name · nav · meta (last-scan, ticker count)
- Filters row: preset pills · filter chips (terse: `size:any move:≥3% vol:≥2×`)
- Section header (`▲ PICKS`) in `--accent`, uppercase, letter-spacing 0.15em
- Each row is one ticker:
  - cols: `rank | symbol | side | price | %chg | sparkline | score | icons`
  - grid template: `24px 60px 18px 80px 70px 90px 36px 1fr`
  - row gap 10px, padding `3px 0`, dotted bottom border
- Sparkline is unicode block chars `▁▂▃▄▅▆▇` — instant render, no SVG
- All numbers right-align in their cell

### Sections in order
1. PICKS (top 12, short-term)
2. TOP 20 MOVERS (by `abs(pctChange)`)
3. WATCHLIST (≤ 10)
4. ALL SCAN (collapsed by default)

---

## 2. Editorial direction

**Vibe:** Markets back-page of a print newspaper. Big serif masthead, three columns, daily lede.

### Tokens
```css
--bg:        #f8f3e6;     /* warm cream */
--rule:      #c9c2af;
--rule-strong: #1a1a1a;
--ink:       #1a1a1a;
--ink-2:     #5a5a52;
--green:     #1d8a4b;
--red:       #c93838;
--font-display: 'Playfair Display', 'GT Sectra', Georgia, serif;
--font-body:    Georgia, 'Source Serif Pro', serif;
--font-mono:    'JetBrains Mono', monospace;
```

### Layout
- Masthead: title (Playfair Display 900, 38px), volume/date/meta in caps tracked .12em
- Double-rule (`border-bottom: 3px double`) below masthead
- **Lede band** spanning all columns:
  - hero headline ("Risk-on tape, breadth narrow") + 1 paragraph
  - 2 stat tiles: top mover, long/short count
- **3-column body** (`column-count: 3; column-rule: 1px solid var(--rule)`):
  - col 1: Short-term Picks
  - col 2: Top 20 Movers
  - col 3: Watchlist + footnote legend
- Each pick:
  - grid `18px 1fr auto` rows: `rank · ticker · pct` / `meta line italic 11px` / `chart 24px`
  - sparkline as thin SVG polyline (no fill, 1.2px stroke)
- Footnote glyphs (`† ‡ §`) replace badges — legend printed once at bottom

---

## 3. Conviction direction

**Vibe:** Confident consumer fintech. The 6 picks dominate; everything else collapses.

### Tokens
```css
--bg:           #fafaf7;
--card:         #ffffff;
--card-long:    #f0faf3;
--card-short:   #fdf2f0;
--ink:          #1a1a1a;
--ink-2:        #5a5a52;
--green:        #1d8a4b;
--red:          #c93838;
--font-display: 'Playfair Display', serif;   /* % change numerals */
--font-script:  'Caveat', cursive;            /* tickers, casual */
--font-mono:    'JetBrains Mono', monospace;
--font-ui:      'Inter', -apple-system, sans-serif;
```

> Note: in production swap `Caveat` for a humanist sans like `Söhne` or `Aktiv Grotesk` for the ticker — the wireframe uses Caveat for sketch-feel only.

### Layout
- Sticky filter strip (8 chips: window · tickers · preset · size · move · vol · news · last-scan)
- **Hero grid**: 3 cols × 2 rows of pick cards, each ~220px tall
- Card anatomy:
  - top-left: `#N · pick` (mono, dim) → ticker (60px display) → price (mono, dim)
  - top-right: `▲ long` / `▼ short` pill (1.5px border, current color)
  - middle-left: % change in Playfair 900, 44px
  - bottom-left: `conviction <b>7</b>` (display weight on the number)
  - bottom-right: row of 2-3 icons
  - background: sparkline SVG, bottom 60% of card, opacity .35, color = direction
  - card bg tint matches direction (`--card-long` / `--card-short`)
- **Below the fold**: 2 cols
  - col 1: Top 20 movers, thin sortable rows (6-col grid `22px 56px 60px 80px 60px 1fr` → rank · ticker · **block-spark** · price · pct · icons)
  - col 2: Watchlist (same row treatment)
- **Sparkline strategy is hybrid**:
  - Hero cards → full SVG polyline as background (`opacity .35`, color = direction)
  - Thin rows → unicode block chars `▁▂▃▄▅▆▇` (mono 14px, color = direction)
  - Rationale: zero render cost in the dense rows, visual richness in the heroes

---

## 4. Heat Grid direction

**Vibe:** Trading-floor wall. Color does the talking. Treemap-ish.

### Tokens
```css
--bg:        #1a1a1a;
--bg-cell-n: #2a2a28;
--fg:        #f5f1e8;
--accent:    #f6c945;
--font-mono:    'JetBrains Mono', monospace;
--font-script:  'Caveat', cursive;  /* section headings + ticker */
```

### Color scale (perceptually uniform, mapped to |%chg|)
| Bin       | Class    | Hex       |
|-----------|----------|-----------|
| 0–2% up   | `.h-g1`  | `#6cc88e` (dark-on-light) |
| 2–5% up   | `.h-g2`  | `#2fa55e` |
| 5–10% up  | `.h-g3`  | `#1d8a4b` |
| 10–15% up | `.h-g4`  | `#137b3c` |
| 15%+ up   | `.h-g5`  | `#0a5a2e` |
| 0–2% dn   | `.h-r1`  | `#e5a0a0` (dark-on-light) |
| 2–5% dn   | `.h-r2`  | `#d96868` |
| 5–10% dn  | `.h-r3`  | `#c93838` |
| 10–15% dn | `.h-r4`  | `#a01f1f` |
| 15%+ dn   | `.h-r5`  | `#7a1414` |
| flat      | `.h-n`   | `#2a2a28` |

### Layout
- Toolbar: app name · scan meta · `size by:` toggle (`conviction | volume | |%chg|`)
- Three stacked grids: **picks · movers · watchlist**
- Each grid: `grid-template-columns: repeat(8, 1fr)`, `grid-auto-rows: 70px`, `gap: 3px`
- Cell size rules:
  - Picks #1-3 → `span 2 / span 2` (2×2)
  - Picks #4-6 → `span 2` (2×1)
  - Picks #7+ → 1×1
  - Movers → uniform 1×1 (color carries rank visually)
  - Watchlist → top 3 are 2×1, rest 1×1
- Cell content: ticker (Caveat 22px, white) + `%chg · s7` (mono 12px) + icon row pinned top-right (mono 11px)
- Click a cell → open ticker detail (out of scope for this redesign)

---

## 5. Components to build (any direction)

| Component               | Notes                                                                 |
|-------------------------|-----------------------------------------------------------------------|
| `TopBar`                | nav, last-scan meta, color-mode toggle, ticker-search                 |
| `FilterStrip`           | preset chips + size/move/vol/news/vwap chip-groups                    |
| `Section` (`title`, `meta`) | h-rule + saffron/heading + right-aligned meta                     |
| `TickerRow`             | terminal & editorial. Props match the `Ticker` type above             |
| `PickCard`              | conviction direction only. Props: ticker, side, score, sparkline      |
| `HeatCell`              | heat-grid only. Computes bin from `pctChange`, applies class          |
| `Sparkline`             | accepts `treatment: 'block' | 'line' | 'range' | 'candle'`            |
| `IconCluster`           | renders ≤ 3 flag icons + " +N" overflow                               |

---

## 6. Suggested implementation order (for Claude Code)

1. **Pick a direction.** If undecided, build **Conviction** first — it shares most components with the current design (filter strip + cards) so least invasive.
2. Extract today's `Card`/`Row` into the components above.
3. Replace the badge cluster with `IconCluster` reading from the `flags` array.
4. Swap sparkline implementation behind a single `Sparkline` component so you can A/B all four treatments later via the tweaks panel.
5. Apply the chosen direction's tokens via CSS variables on `:root` (or `[data-theme="terminal"]` etc. so you can toggle).
6. Heat Grid is the biggest reskin — leave for last unless that's the chosen direction.

---

## 7. What I did NOT change

- The data pipeline / scanner logic
- Tabs structure (Scan / Macro / Weekly / Perf)
- Presets (All / Gap & Go / Catalyst / High Conviction / Mid/Small / Burst)
- The "All scan (753)" collapsed table at the bottom — stays as the escape hatch in every direction
