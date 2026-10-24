-- Headline commerce KPIs for an inclusive date window.
-- Revenue in USD; orders are distinct transaction ids on purchase events.
WITH events AS (
  SELECT
    CONCAT(
      user_pseudo_id, '-',
      CAST((SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)
    ) AS session_id,
    user_pseudo_id,
    event_name,
    ecommerce.purchase_revenue AS purchase_revenue,
    ecommerce.total_item_quantity AS total_item_quantity,
    ecommerce.transaction_id AS transaction_id
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
)
SELECT
  IFNULL(SUM(IF(event_name = 'purchase', purchase_revenue, 0)), 0) AS revenue,
  COUNT(DISTINCT IF(
    event_name = 'purchase' AND transaction_id IS NOT NULL AND transaction_id != '(not set)',
    transaction_id, NULL)) AS orders,
  IFNULL(SUM(IF(event_name = 'purchase', total_item_quantity, 0)), 0) AS units,
  COUNT(DISTINCT IF(event_name = 'purchase', user_pseudo_id, NULL)) AS purchasers,
  COUNT(DISTINCT session_id) AS sessions,
  COUNT(DISTINCT IF(event_name = 'purchase', session_id, NULL)) AS purchasing_sessions
FROM events
