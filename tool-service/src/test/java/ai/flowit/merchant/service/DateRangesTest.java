package ai.flowit.merchant.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import ai.flowit.merchant.bigquery.QueryParam;
import ai.flowit.merchant.v1.DateRange;
import io.grpc.Status;
import io.grpc.StatusRuntimeException;
import java.time.LocalDate;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

class DateRangesTest {

  @Test
  void fillsDatasetWindowWhenRangeIsMissing() {
    DateRanges.Applied applied = DateRanges.resolve(null);

    assertEquals(LocalDate.of(2020, 11, 1), applied.start());
    assertEquals(LocalDate.of(2021, 1, 31), applied.end());
    assertFalse(applied.clamped());
  }

  @Test
  void fillsDatasetWindowWhenRangeIsEmpty() {
    DateRanges.Applied applied = DateRanges.resolve(DateRange.getDefaultInstance());

    assertEquals(DateRanges.START, applied.start());
    assertEquals(DateRanges.END, applied.end());
    assertFalse(applied.clamped());
  }

  @Test
  void fillsOnlyTheMissingBound() {
    DateRanges.Applied onlyStart = DateRanges.resolve(DateRange.newBuilder().setStartDate("2021-01-10").build());
    assertEquals(LocalDate.of(2021, 1, 10), onlyStart.start());
    assertEquals(DateRanges.END, onlyStart.end());
    assertFalse(onlyStart.clamped());

    DateRanges.Applied onlyEnd = DateRanges.resolve(DateRange.newBuilder().setEndDate("2020-12-01").build());
    assertEquals(DateRanges.START, onlyEnd.start());
    assertEquals(LocalDate.of(2020, 12, 1), onlyEnd.end());
    assertFalse(onlyEnd.clamped());
  }

  @Test
  void keepsRangeInsideWindowUnchanged() {
    DateRanges.Applied applied = DateRanges.resolve(range("2020-12-01", "2020-12-24"));

    assertEquals(LocalDate.of(2020, 12, 1), applied.start());
    assertEquals(LocalDate.of(2020, 12, 24), applied.end());
    assertFalse(applied.clamped());
  }

  @Test
  void clampsBothBoundsToWindow() {
    DateRanges.Applied applied = DateRanges.resolve(range("2019-01-01", "2022-12-31"));

    assertEquals(DateRanges.START, applied.start());
    assertEquals(DateRanges.END, applied.end());
    assertTrue(applied.clamped());
  }

  @Test
  void clampsOnlyTheOutOfWindowBound() {
    DateRanges.Applied applied = DateRanges.resolve(range("2020-10-01", "2020-11-15"));

    assertEquals(DateRanges.START, applied.start());
    assertEquals(LocalDate.of(2020, 11, 15), applied.end());
    assertTrue(applied.clamped());
  }

  @Test
  void convertsToTableSuffixParams() {
    Map<String, QueryParam> params = DateRanges.resolve(range("2020-12-05", "2021-01-07")).toParams();

    assertEquals(QueryParam.string("20201205"), params.get("start_suffix"));
    assertEquals(QueryParam.string("20210107"), params.get("end_suffix"));
    assertEquals(2, params.size());
  }

  @Test
  void protoRoundTripUsesIsoDates() {
    DateRange proto = DateRanges.resolve(range("2020-12-05", "2021-01-07")).toProto();

    assertEquals("2020-12-05", proto.getStartDate());
    assertEquals("2021-01-07", proto.getEndDate());
  }

  @Test
  void rejectsStartAfterEnd() {
    assertInvalid(() -> DateRanges.resolve(range("2020-12-10", "2020-12-01")));
  }

  @ParameterizedTest
  @CsvSource({
      "2020/12/01, 2020-12-10",
      "2020-12-01, 10-12-2020",
      "2020-02-30, 2020-12-10",
      "yesterday, 2020-12-10",
      "20201201, 2020-12-10",
  })
  void rejectsUnparsableDates(String start, String end) {
    assertInvalid(() -> DateRanges.resolve(range(start, end)));
  }

  @Test
  void rejectsRangeEntirelyOutsideWindow() {
    assertInvalid(() -> DateRanges.resolve(range("2022-01-01", "2022-02-01")));
    assertInvalid(() -> DateRanges.resolve(range("2019-01-01", "2019-02-01")));
  }

  @Test
  void limitDefaultsToTenWhenZero() {
    assertEquals(10, DateRanges.resolveLimit(0));
    assertEquals(1, DateRanges.resolveLimit(1));
    assertEquals(50, DateRanges.resolveLimit(50));
  }

  @ParameterizedTest
  @ValueSource(ints = {-1, 51, 1000, Integer.MIN_VALUE})
  void rejectsLimitOutsideRange(int limit) {
    assertInvalid(() -> DateRanges.resolveLimit(limit));
  }

  private static DateRange range(String start, String end) {
    return DateRange.newBuilder().setStartDate(start).setEndDate(end).build();
  }

  private static void assertInvalid(Runnable action) {
    StatusRuntimeException e = assertThrows(StatusRuntimeException.class, action::run);
    assertEquals(Status.Code.INVALID_ARGUMENT, e.getStatus().getCode(), e.getMessage());
  }
}
