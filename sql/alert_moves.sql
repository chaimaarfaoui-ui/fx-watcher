-- Rate-move alerts. Returns ONLY alerts not sent before.
-- latest -> triggered (moved at least the pair's threshold) -> claimed (logged; already-logged ones are skipped)
WITH latest AS (
    SELECT DISTINCT ON (base, quote) *
    FROM fx_moves
    ORDER BY base, quote, provider_updated_at DESC
), triggered AS (
    SELECT l.*
    FROM latest l
    JOIN watch_pairs w ON w.base = l.base AND w.quote = l.quote
    WHERE w.active
      AND l.pct_change IS NOT NULL
      AND abs(l.pct_change) >= w.threshold_pct
), claimed AS (
    INSERT INTO alerts_log (kind, base, quote, provider_updated_at, metric)
    SELECT 'move', base, quote, provider_updated_at, pct_change FROM triggered
    ON CONFLICT (kind, base, quote, provider_updated_at) DO NOTHING
    RETURNING base, quote, provider_updated_at
)
SELECT t.base, t.quote, t.rate, t.prev_rate, t.pct_change,
       COALESCE(e.total, 0)                                    AS monthly_exposure,
       round(COALESCE(e.total, 0) * (t.rate - t.prev_rate), 0) AS extra_monthly_cost
FROM triggered t
JOIN claimed c USING (base, quote, provider_updated_at)
LEFT JOIN (SELECT currency, sum(monthly_amount) AS total
           FROM import_exposure GROUP BY currency) e ON e.currency = t.base
