package ai.flowit.merchant.service;

import ai.flowit.merchant.bigquery.QueryParam;
import ai.flowit.merchant.v1.DateRange;
import io.grpc.Status;
import io.grpc.StatusRuntimeException;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.format.ResolverStyle;
import java.util.LinkedHashMap;
import java.util.Map;

/** Date-window handling for the GA4 sample: filling, clamping, validation and `_TABLE_SUFFIX` params. */
public final class DateRanges {

  /** First day present in the public sample. */
  public static final LocalDate START = LocalDate.of(2020, 11, 1);
  /** Last day present in the public sample. */
  public static final LocalDate END = LocalDate.of(2021, 1, 31);

  public static final String PARAM_START_SUFFIX = "start_suffix";
  public static final String PARAM_END_SUFFIX = "end_suffix";

  public static final int DEFAULT_LIMIT = 10;
  public static final int MIN_LIMIT = 1;
  public static final int MAX_LIMIT = 50;

  private static final DateTimeFormatter ISO = DateTimeFormatter.ofPattern("uuuu-MM-dd").withResolverStyle(ResolverStyle.STRICT);
  private static final DateTimeFormatter SUFFIX = DateTimeFormatter.ofPattern("uuuuMMdd");

  private DateRanges() {}

  /** The range actually queried after filling defaults and clamping to the dataset window. */
  public record Applied(LocalDate start, LocalDate end, boolean clamped) {

    public DateRange toProto() {
      return DateRange.newBuilder().setStartDate(ISO.format(start)).setEndDate(ISO.format(end)).build();
    }

    public String startSuffix() {
      return SUFFIX.format(start);
    }

    public String endSuffix() {
      return SUFFIX.format(end);
    }

    /** Named parameters for `_TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix`. */
    public Map<String, QueryParam> toParams() {
      Map<String, QueryParam> params = new LinkedHashMap<>();
      params.put(PARAM_START_SUFFIX, QueryParam.string(startSuffix()));
      params.put(PARAM_END_SUFFIX, QueryParam.string(endSuffix()));
      return params;
    }
  }

  /** The full dataset window. */
  public static Applied full() {
    return new Applied(START, END, false);
  }

  /**
   * Fills missing bounds with the dataset window and clamps the rest into it.
   *
   * @throws StatusRuntimeException INVALID_ARGUMENT for unparsable dates, start after end, or a range
   *     that does not overlap the dataset window at all
   */
  public static Applied resolve(DateRange requested) {
    LocalDate start = requested == null || requested.getStartDate().isBlank()
        ? START
        : parse(requested.getStartDate(), "start_date");
    LocalDate end = requested == null || requested.getEndDate().isBlank()
        ? END
        : parse(requested.getEndDate(), "end_date");

    if (start.isAfter(end)) {
      throw invalid("start_date " + start + " is after end_date " + end);
    }
    if (end.isBefore(START) || start.isAfter(END)) {
      throw invalid("date range " + start + ".." + end + " is outside the dataset window " + START + ".." + END);
    }

    boolean clamped = false;
    if (start.isBefore(START)) {
      start = START;
      clamped = true;
    }
    if (end.isAfter(END)) {
      end = END;
      clamped = true;
    }
    return new Applied(start, end, clamped);
  }

  /** Validates a row limit: 0 means the default, otherwise it must be within 1..50. */
  public static int resolveLimit(int limit) {
    if (limit == 0) {
      return DEFAULT_LIMIT;
    }
    if (limit < MIN_LIMIT || limit > MAX_LIMIT) {
      throw invalid("limit must be between " + MIN_LIMIT + " and " + MAX_LIMIT + ", got " + limit);
    }
    return limit;
  }

  private static LocalDate parse(String value, String field) {
    try {
      return LocalDate.parse(value.trim(), ISO);
    } catch (DateTimeParseException e) {
      throw invalid(field + " must be an ISO-8601 calendar date (YYYY-MM-DD), got '" + value + "'");
    }
  }

  static StatusRuntimeException invalid(String message) {
    return Status.INVALID_ARGUMENT.withDescription(message).asRuntimeException();
  }
}
