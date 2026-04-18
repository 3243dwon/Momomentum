# Momentum

A personal momentum scanner with news synthesis. Built for one trader.

When a Fed pause hits the wire, a generic scanner shows you the headline.
This shows you who benefits — with the mechanism, the confidence, and the
horizon — alongside the price action that triggered the alert.

```
ticker scan → routing → news ingest → classify → synthesize → macro reasoning
                                                                      ↓
                                                           alerts + dashboard
```

Three signal classes drive alerts: threshold (watchlist + big moves),
delta (rank changes between scans), and macro (events with second-order
beneficiary breakdowns). All throttled, all auditable, all opinionated.

Mobile-first PWA with light/dark, sortable tables, per-ticker drill-down,
and a separate macro-events view. Runs on its own — no babysitting.

---

Personal scanner. Not investment advice. Source by request.
