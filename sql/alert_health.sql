-- Watchdog: warns (max once per day) if no real API data arrived for 36 hours.
WITH stale AS (
    SELECT 'stale_data'::text AS kind,
           current_date       AS day,
           CASE WHEN max(provider_updated_at) IS NULL
                THEN 'No API data has ever been collected'
                ELSE 'Latest API rate is from ' || to_char(max(provider_updated_at), 'YYYY-MM-DD HH24:MI')
                     || ' UTC (about ' || round(extract(epoch FROM now() - max(provider_updated_at)) / 3600)
                     || ' hours ago)'
           END                AS detail
    FROM fx_rates
    WHERE source = 'api'
    HAVING max(provider_updated_at) IS NULL
        OR max(provider_updated_at) < now() - interval '36 hours'
), claimed AS (
    INSERT INTO system_alerts (kind, day, detail)
    SELECT kind, day, detail FROM stale
    ON CONFLICT (kind, day) DO NOTHING
    RETURNING detail
)
SELECT detail FROM claimed
