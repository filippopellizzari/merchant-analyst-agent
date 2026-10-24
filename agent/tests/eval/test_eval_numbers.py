"""Extractor tests: every number the agent could write must be found, and
things that look like numbers but are not (dates, years, list markers, times)
must be ignored."""

from merchant_eval.numbers import NumberMention, extract_numbers


def values(text):
    return [m.value for m in extract_numbers(text)]


def kinds(text):
    return [(m.value, m.kind) for m in extract_numbers(text)]


def test_dollar_with_thousands_and_cents():
    (m,) = extract_numbers("Revenue was $12,345.67 in total.")
    assert m == NumberMention(
        raw="$12,345.67", value=12345.67, kind="money", start=12, end=22, decimals=2
    )


def test_usd_prefix_and_suffix():
    assert kinds("USD 12,345.67 and 99.5 USD") == [(12345.67, "money"), (99.5, "money")]


def test_plain_thousands_separated_integer_is_one_number():
    (m,) = extract_numbers("12,345 orders")
    assert m.value == 12345 and m.kind == "count" and m.decimals == 0


def test_decimal_with_thousands_separator_is_one_number():
    (m,) = extract_numbers("about 1,234.5 units")
    assert (m.value, m.decimals) == (1234.5, 1)


def test_percent():
    (m,) = extract_numbers("conversion was 12.3%")
    assert (m.value, m.kind, m.decimals) == (12.3, "percent", 1)


def test_percent_word():
    (m,) = extract_numbers("conversion was 2 percent")
    assert (m.value, m.kind) == (2.0, "percent")


def test_k_and_m_scale():
    ms = extract_numbers("1.2k sessions, 1.2K users, 3.4M events, 2B rows")
    assert [(m.value, m.scale, m.decimals) for m in ms] == [
        (1200.0, 1000.0, 1),
        (1200.0, 1000.0, 1),
        (3_400_000.0, 1_000_000.0, 1),
        (2_000_000_000.0, 1_000_000_000.0, 0),
    ]
    assert all(m.kind == "plain" for m in ms)


def test_money_with_scale():
    (m,) = extract_numbers("$1.2k")
    assert (m.value, m.kind, m.scale) == (1200.0, "money", 1000.0)


def test_scale_suffix_not_part_of_word():
    assert values("weighs 1.2kg") == [] or values("weighs 1.2kg") == [1.2]
    # never interpreted as 1200
    assert 1200.0 not in values("weighs 1.2kg")


def test_negative_numbers_ascii_and_unicode_minus():
    ms = extract_numbers("change of -5.5% and −12 orders, and -$300")
    assert [(m.value, m.kind) for m in ms] == [
        (-5.5, "percent"),
        (-12.0, "count"),
        (-300.0, "money"),
    ]
    assert ms[1].raw == "−12"


def test_plus_minus_percent():
    assert kinds("+12.3% vs −4.0%") == [(12.3, "percent"), (-4.0, "percent")]


def test_composite_phrase():
    ms = extract_numbers("$1,234.50 (+12.3% vs 1.1k)")
    assert [(m.raw, m.value, m.kind) for m in ms] == [
        ("$1,234.50", 1234.5, "money"),
        ("+12.3%", 12.3, "percent"),
        ("1.1k", 1100.0, "plain"),
    ]


def test_markdown_table():
    text = (
        "| Rank | Product | Revenue | Share |\n"
        "|---|---|---|---|\n"
        "| 1 | Hoodie | $1,234.50 | 12.3% |\n"
        "| 2 | Mug | $999.00 | 9.9% |\n"
    )
    assert kinds(text) == [
        (1.0, "count"),
        (1234.5, "money"),
        (12.3, "percent"),
        (2.0, "count"),
        (999.0, "money"),
        (9.9, "percent"),
    ]


def test_iso_and_slash_dates_excluded():
    text = "From 2020-12-01 to 2020/12/31 and 12/01/2020 and 01-12-2020."
    assert values(text) == []


def test_standalone_year_excluded():
    assert values("Sales in 2020 were strong; 2021 too.") == []


def test_year_in_month_context_excluded():
    assert values("In December 2020 and Nov 2020, as well as Dec. 2020.") == []


def test_day_of_month_excluded():
    assert values("Peak on December 25 and on 1 January 2021; Dec 5th was weak.") == []


def test_year_like_money_or_percent_kept():
    assert kinds("$2020 and 2020% and 2,020 units") == [
        (2020.0, "money"),
        (2020.0, "percent"),
        (2020.0, "count"),
    ]


def test_list_markers_excluded():
    text = "Top items:\n1. Hoodie $10\n2) Mug $20\n  3. Cap $30\n## 4. Heading\n"
    assert kinds(text) == [(10.0, "money"), (20.0, "money"), (30.0, "money")]


def test_times_excluded():
    assert values("Traffic peaks at 10:30 and 18:05:59.") == []


def test_hex_hash_excluded():
    assert values("sql_hash 3f9a1c2b4d5e6f70 and 1a2b3c4d") == []


def test_numbers_glued_to_letters_ignored():
    assert values("Q4 FY21 v2 abc123") == []


def test_ordinals_ignored():
    assert values("the 5th best and 1st overall") == []


def test_positions_are_exact_spans():
    text = "A: $5.00; B: 7"
    ms = extract_numbers(text)
    assert [text[m.start : m.end] for m in ms] == ["$5.00", "7"]
    assert [m.raw for m in ms] == ["$5.00", "7"]


def test_top_n_is_returned_by_extractor():
    # the matcher decides whether "5" is grounded (limit arg), the extractor keeps it
    assert values("Here are the top 5 products") == [5.0]


def test_trailing_period_not_a_decimal():
    (m,) = extract_numbers("There were 1234.")
    assert (m.value, m.decimals, m.raw) == (1234.0, 0, "1234")


def test_leading_dot_decimal():
    (m,) = extract_numbers("rate .05")
    assert (m.value, m.decimals) == (0.05, 2)


def test_no_numbers():
    assert extract_numbers("The dataset is the Google Merchandise Store sample.") == []
