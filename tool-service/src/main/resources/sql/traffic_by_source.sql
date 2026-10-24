-- Sessions, purchasers, orders and revenue per traffic source / medium, ordered by sessions.
WITH events AS (
  SELECT
    IFNULL(traffic_source.source, '(not set)') AS source,
    IFNULL(traffic_source.medium, '(not set)') AS medium,
    CONCAT(
      user_pseudo_id, '-',
      CAST((SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)
    ) AS session_id,
    user_pseudo_id,
    event_name,
    ecommerce.purchase_revenue AS purchase_revenue,
    ecommerce.transaction_id AS transaction_id
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
)
SELECT
  source,
  medium,
  COUNT(DISTINCT session_id) AS sessions,
  COUNT(DISTINCT IF(event_name = 'purchase', user_pseudo_id, NULL)) AS purchasers,
  COUNT(DISTINCT IF(
    event_name = 'purchase' AND transaction_id IS NOT NULL AND transaction_id != '(not set)',
    transaction_id, NULL)) AS orders,
  IFNULL(SUM(IF(event_name = 'purchase', purchase_revenue, 0)), 0) AS revenue,
  IFNULL(SAFE_DIVIDE(
    COUNT(DISTINCT IF(event_name = 'purchase', session_id, NULL)),
    COUNT(DISTINCT session_id)), 0) AS conversion_rate
FROM events
GROUP BY source, medium
ORDER BY sessions DESC, source, medium
LIMIT @limit
