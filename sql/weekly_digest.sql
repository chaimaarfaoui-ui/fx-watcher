-- One ready-to-send message: latest rate, 7-day change, position in the 30-day range, cost vs budget.
WITH latest AS (
    SELECT DISTINCT ON (base, quote) base, quote, rate, provider_updated_at
    FROM fx_rates ORDER BY base, quote, provider_updated_at DESC
), week_ago AS (
    SELECT DISTINCT ON (r.base, r.quote) r.base, r.quote, r.rate
    FROM fx_rates r JOIN latest l ON l.base = r.base AND l.quote = r.quote
    WHERE r.provider_updated_at <= l.provider_updated_at - interval '7 days'
    ORDER BY r.base, r.quote, r.provider_updated_at DESC
), range30 AS (
    SELECT r.base, r.quote, min(r.rate) AS lo, max(r.rate) AS hi
    FROM fx_rates r JOIN latest l ON l.base = r.base AND l.quote = r.quote
    WHERE r.provider_updated_at >= l.provider_updated_at - interval '30 days'
    GROUP BY r.base, r.quote
), exposure AS (
    SELECT currency, sum(monthly_amount) AS total FROM import_exposure GROUP BY currency
), lines AS (
    SELECT l.base, l.quote,
           l.base || '/' || l.quote || ' ' || round(l.rate, 4)
           || ' | 7d: ' || COALESCE(to_char(100 * (l.rate / w.rate - 1), 'FMS990.00') || '%', 'n/a')
           || ' | 30d range position: '
           || COALESCE(round(100 * (l.rate - r.lo) / NULLIF(r.hi - r.lo, 0))::text || '% (0=low, 100=high)', 'n/a')
           || ' | ' || COALESCE(
                'budget ' || round(b.budget_rate, 4) || ': '
                || to_char(100 * (l.rate / b.budget_rate - 1), 'FMS990.0') || '% '
                || '(' || to_char(COALESCE(e.total, 0) * (l.rate - b.budget_rate), 'FMS999,999,990')
                || ' ' || l.quote || ' per month)',
                'no budget set') AS line
    FROM latest l
    LEFT JOIN week_ago w     ON w.base = l.base AND w.quote = l.quote
    LEFT JOIN range30 r      ON r.base = l.base AND r.quote = l.quote
    LEFT JOIN budget_rates b ON b.base = l.base AND b.quote = l.quote
    LEFT JOIN exposure e     ON e.currency = l.base
)
SELECT 'FX weekly summary ' || to_char(now(), 'YYYY-MM-DD') || E'\n'
       || COALESCE(string_agg(line, E'\n' ORDER BY base, quote), 'No data yet')
       || E'\n\nMid-market rates, not what your bank charges. Rates by exchangerate-api.com' AS message
FROM lines
