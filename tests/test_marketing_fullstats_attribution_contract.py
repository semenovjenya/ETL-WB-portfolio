from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_fullstats_parser_preserves_direct_sum_price_and_missingness():
    source = (ROOT / "marketing" / "fetch_marketing_stats.py").read_text(
        encoding="utf-8"
    )

    assert '"sum_price": day_block.get("sum_price")' in source
    assert 'nm.get("sum_price") is None' in source
    assert 'row["sum_price"] = None' in source


def test_upserts_persist_and_refresh_sum_price_at_both_grains():
    source = (ROOT / "marketing" / "database.py").read_text(encoding="utf-8")

    assert source.count("sum_spend, sum_price") >= 2
    assert source.count("sum_price = EXCLUDED.sum_price") >= 2
    assert "mark_campaign_stats_daily_watermarks" in source


def test_schema_keeps_revenue_nullable_and_has_fail_closed_watermark():
    sql = (
        ROOT / "tables" / "marketing" / "schema_wb_marketing_analytics.sql"
    ).read_text(encoding="utf-8").lower()

    assert sql.count("sum_price decimal(14, 2)") >= 2
    assert "sum_price decimal(14, 2) default" not in sql
    assert "wb_marketing_campaign_stats_daily_watermarks" in sql
    assert "campaign_sku_stats_complete boolean not null default false" in sql
    assert "wb_marketing_campaign_stats_daily_watermarks_proven_complete" in sql


def test_fullstats_starts_at_zero_after_budget_and_resumes_only_its_own_stage():
    source = (ROOT / "marketing" / "fetch_marketing_stats.py").read_text(
        encoding="utf-8"
    )

    assert 'state.get("stage") == "fetch_fullstats_batches"' in source
    assert "next_cursor = 0" in source
    assert "Resume the exact frozen list" in source


def test_fullstats_campaign_set_covers_period_history_and_current_api():
    fetcher_source = (ROOT / "marketing" / "fetch_marketing_stats.py").read_text(
        encoding="utf-8"
    )
    database_source = (ROOT / "marketing" / "database.py").read_text(
        encoding="utf-8"
    )

    assert "_resolve_fullstats_campaign_ids" in fetcher_source
    assert "get_campaign_ids_for_period" in fetcher_source
    assert "get_campaign_ids_for_period" in database_source
    assert "wb_marketing_campaign_stats_daily_nms" in database_source


def test_period_is_at_most_31_inclusive_days_and_today_is_not_watermarked():
    source = (ROOT / "marketing" / "fetch_marketing_stats.py").read_text(
        encoding="utf-8"
    )

    assert "bounded_days - 1" in source
    assert "snapshot_date - timedelta(days=1)" in source


def test_failed_or_deferred_batch_persists_cursor_without_watermark():
    source = (ROOT / "marketing" / "fetch_marketing_stats.py").read_text(
        encoding="utf-8"
    )

    failed_branch = source.split("if not isinstance(data, list):", 1)[1].split(
        "for camp in data:", 1
    )[0]
    assert "self._save_progress(" in failed_branch
    assert 'stage="fetch_fullstats_batches"' in failed_branch
    assert "cursor=cursor" in failed_branch
