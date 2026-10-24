-- Best-selling items on purchase events, ranked by @metric (REVENUE | UNITS | ORDERS).
SELECT
  item.item_name AS item_name,
  ANY_VALUE(item.item_category) AS item_category,
  IFNULL(SUM(item.item_revenue), 0) AS revenue,
  IFNULL(SUM(item.quantity), 0) AS units,
  COUNT(DISTINCT IF(
    ecommerce.transaction_id IS NOT NULL AND ecommerce.transaction_id != '(not set)',
    ecommerce.transaction_id, NULL)) AS orders
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`,
  UNNEST(items) AS item
WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
  AND event_name = 'purchase'
  AND item.item_name IS NOT NULL
GROUP BY item_name
ORDER BY
  CASE @metric
    WHEN 'UNITS' THEN CAST(units AS FLOAT64)
    WHEN 'ORDERS' THEN CAST(orders AS FLOAT64)
    ELSE revenue
  END DESC,
  item_name
LIMIT @limit
