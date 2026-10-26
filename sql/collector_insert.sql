INSERT INTO fx_rates (base, quote, rate, provider_updated_at)
SELECT $1, w.quote, (($2::jsonb) ->> w.quote)::numeric, to_timestamp($3::bigint)
FROM watch_pairs w
WHERE w.base = $1 AND w.active AND ($2::jsonb) ? w.quote
ON CONFLICT DO NOTHING
