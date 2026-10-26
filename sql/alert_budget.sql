-- Budget alert: fires when the rate CROSSES above budget + tolerance (not every day while it stays above).
WITH latest AS (
    SELECT DISTINCT ON (base, quote) *
    FROM fx_moves
    ORDER BY base, quote, provider_updated_at DESC
), crossed AS (
    SELECT l.base, l.quote, l.rate, l.prev_rate, l.provider_updated_at,
           b.budget_rate, b.tolerance_pct
    FROM latest l
    JOIN budget_rates b ON b.base = l.base AND b.quote = l.quote
    WHERE l.rate > b.budget_rate * (1 + b.tolerance_pct / 100)
      AND (l.prev_rate IS NULL OR l.prev_rate <= b.budget_rate * (1 + b.tolerance_pct / 100))
), claimed AS (
    INSERT INTO alerts_log (kind, base, quote, provider_updated_at, metric)
    SELECT 'budget', base, quote, provider_updated_at, round(100 * (rate / budget_rate - 1), 4)
    FROM crossed
    ON CONFLICT (kind, base, quote, provider_updated_at) DO NOTHING
    RETURNING base, quote, provider_updated_at
)
SELECT c.base, c.quote, c.rate, c.budget_rate,
       round(100 * (c.rate / c.budget_rate - 1), 2)                       AS pct_over_budget,
       COALESCE(e.total, 0)                                                AS monthly_exposure,
       round(COALESCE(e.total, 0) * (c.rate - c.budget_rate), 0)           AS extra_vs_budget
FROM crossed c
JOIN claimed k USING (base, quote, provider_updated_at)
LEFT JOIN (SELECT currency, sum(monthly_amount) AS total
           FROM import_exposure GROUP BY currency) e ON e.currency = c.base
