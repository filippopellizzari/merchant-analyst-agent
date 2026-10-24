package ai.flowit.merchant.bigquery;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import com.google.cloud.bigquery.Field;
import com.google.cloud.bigquery.FieldList;
import com.google.cloud.bigquery.FieldValue;
import com.google.cloud.bigquery.FieldValueList;
import com.google.cloud.bigquery.QueryParameterValue;
import com.google.cloud.bigquery.StandardSQLTypeName;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

/** Covers the pure conversion logic of the real gateway; the network path is covered by the bq-tagged test. */
class BigQueryGatewayImplTest {

  @Test
  void convertsRowsUsingSchemaTypes() {
    FieldList fields = FieldList.of(
        Field.of("name", StandardSQLTypeName.STRING),
        Field.of("count", StandardSQLTypeName.INT64),
        Field.of("revenue", StandardSQLTypeName.FLOAT64),
        Field.of("flag", StandardSQLTypeName.BOOL),
        Field.of("missing", StandardSQLTypeName.STRING));
    FieldValueList row = FieldValueList.of(List.of(
        FieldValue.of(FieldValue.Attribute.PRIMITIVE, "Hoodie"),
        FieldValue.of(FieldValue.Attribute.PRIMITIVE, "42"),
        FieldValue.of(FieldValue.Attribute.PRIMITIVE, "12.5"),
        FieldValue.of(FieldValue.Attribute.PRIMITIVE, "true"),
        FieldValue.of(FieldValue.Attribute.PRIMITIVE, null)), fields);

    List<Map<String, Object>> rows = BigQueryGatewayImpl.toRows(fields, List.of(row));

    assertEquals(1, rows.size());
    Map<String, Object> mapped = rows.get(0);
    assertEquals("Hoodie", mapped.get("name"));
    assertEquals(42L, mapped.get("count"));
    assertEquals(12.5d, mapped.get("revenue"));
    assertEquals(true, mapped.get("flag"));
    assertNull(mapped.get("missing"));
  }

  @Test
  void mapsQueryParamsToBigQueryTypes() {
    QueryParameterValue s = BigQueryGatewayImpl.toParameterValue(QueryParam.string("20201101"));
    QueryParameterValue i = BigQueryGatewayImpl.toParameterValue(QueryParam.int64(10));

    assertEquals(StandardSQLTypeName.STRING, s.getType());
    assertEquals("20201101", s.getValue());
    assertEquals(StandardSQLTypeName.INT64, i.getType());
    assertEquals("10", i.getValue());
  }
}
