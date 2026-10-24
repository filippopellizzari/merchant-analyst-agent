-- Sessions, orders and revenue per country, ordered by revenue.
WITH events AS (
  SELECT
    IF(geo.country IS NULL OR geo.country = '', '(not set)', geo.country) AS country,
    CONCAT(
      user_pseudo_id, '-',
      CAST((SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)
    ) AS session_id,
    event_name,
    ecommerce.purchase_revenue AS purchase_revenue,
    ecommerce.transaction_id AS transaction_id
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
)
SELECT
  country,
  COUNT(DISTINCT session_id) AS sessions,
  COUNT(DISTINCT IF(
    event_name = 'purchase' AND transaction_id IS NOT NULL AND transaction_id != '(not set)',
    transaction_id, NULL)) AS orders,
  IFNULL(SUM(IF(event_name = 'purchase', purchase_revenue, 0)), 0) AS revenue
FROM events
GROUP BY country
ORDER BY revenue DESC, country
LIMIT @limit
