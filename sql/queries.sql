-- Learning queries. Run them one by one in psql or DBeaver.

-- 1. Latest rate per pair  (DISTINCT ON)
SELECT DISTINCT ON (base, quote) base, quote, rate, provider_updated_at::date AS day
FROM fx_rates ORDER BY base, quote, provider_updated_at DESC;

-- 2. Last 30 days: min / max / average, and where today sits in that range (0% = low, 100% = high)
WITH last30 AS (
    SELECT * FROM fx_rates WHERE provider_updated_at >= (SELECT max(provider_updated_at) FROM fx_rates) - interval '30 days'
), stats AS (
    SELECT base, quote, min(rate) AS lo, max(rate) AS hi, round(avg(rate), 4) AS avg_rate FROM last30 GROUP BY 1, 2
), latest AS (
    SELECT DISTINCT ON (base, quote) base, quote, rate FROM last30 ORDER BY base, quote, provider_updated_at DESC
)
SELECT s.base, s.quote, s.lo, s.hi, s.avg_rate, l.rate AS latest,
       round(100 * (l.rate - s.lo) / NULLIF(s.hi - s.lo, 0), 0) AS pct_of_range
FROM stats s JOIN latest l USING (base, quote);

-- 3. The five biggest moves ever recorded (window function view)
SELECT base, quote, provider_updated_at::date AS day, prev_rate, rate, pct_change
FROM fx_moves WHERE pct_change IS NOT NULL
ORDER BY abs(pct_change) DESC LIMIT 5;

-- 4. Volatility: 7-observation rolling standard deviation of daily % change
SELECT base, quote, provider_updated_at::date AS day, pct_change,
       round(stddev(pct_change) OVER (PARTITION BY base, quote ORDER BY provider_updated_at
                                      ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 4) AS rolling_vol
FROM fx_moves ORDER BY day DESC, base LIMIT 10;

-- 5. Business view: what the monthly foreign-currency bill costs in TND now vs the 30-day average
WITH now_rate AS (
    SELECT DISTINCT ON (base) base AS currency, rate FROM fx_rates WHERE quote = 'TND'
    ORDER BY base, provider_updated_at DESC
), avg30 AS (
    SELECT base AS currency, avg(rate) AS rate FROM fx_rates
    WHERE quote = 'TND' AND provider_updated_at >= (SELECT max(provider_updated_at) FROM fx_rates) - interval '30 days'
    GROUP BY base
)
SELECT e.label, e.currency, e.monthly_amount,
       round(e.monthly_amount * n.rate, 0)               AS cost_now_tnd,
       round(e.monthly_amount * a.rate, 0)               AS cost_30d_avg_tnd,
       round(e.monthly_amount * (n.rate - a.rate), 0)    AS difference_tnd
FROM import_exposure e
JOIN now_rate n USING (currency)
JOIN avg30 a USING (currency);

-- 6. Data quality: which days are missing? (generate_series + LEFT JOIN)
SELECT p.base, p.quote, d::date AS missing_day
FROM watch_pairs p
CROSS JOIN generate_series((SELECT min(provider_updated_at)::date FROM fx_rates),
                           (SELECT max(provider_updated_at)::date FROM fx_rates), interval '1 day') AS d
LEFT JOIN fx_rates r ON r.base = p.base AND r.quote = p.quote AND r.provider_updated_at::date = d::date
WHERE r.id IS NULL AND p.active
ORDER BY p.base, d;
