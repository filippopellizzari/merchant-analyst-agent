-- Dataset-wide totals over the full sample window.
SELECT
  COUNT(*) AS total_events,
  COUNT(DISTINCT CONCAT(
    user_pseudo_id, '-',
    CAST((SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)
  )) AS total_sessions,
  COUNTIF(event_name = 'purchase') AS total_purchases
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
