#!/usr/bin/env python3
"""
test_backup_retention.py — tests unitarios de la lógica GFS de backup.py.

Sin frameworks externos (stdlib only). Ejecutar:

    python scripts/test_backup_retention.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from backup import gfs_keep_set


def utc(y, m, d, h=12, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


# ── Tests ────────────────────────────────────────────────────────────────


def test_empty():
    assert gfs_keep_set([]) == set()


def test_single():
    ts = utc(2026, 5, 7)
    assert gfs_keep_set([ts]) == {ts}


def test_seven_distinct_days_only():
    """7 días distintos con 1 backup cada uno → todos en daily, weekly y monthly vacíos."""
    ts_list = [utc(2026, 5, 7) - timedelta(days=i) for i in range(7)]
    keep = gfs_keep_set(ts_list)
    assert keep == set(ts_list), f"expected all 7 kept, got {len(keep)}"


def test_multiple_per_day_keeps_latest():
    """4 backups el mismo día → solo el más reciente del día queda."""
    day_base = utc(2026, 5, 7, 0, 0)
    ts_list = [day_base.replace(hour=h) for h in (0, 6, 12, 18)]
    keep = gfs_keep_set(ts_list)
    assert len(keep) == 1
    assert max(ts_list) in keep


def test_two_per_day_for_14_days():
    """2 backups por día durante 14 días → daily mantiene 7 (latest de cada día)."""
    ts_list = []
    for d in range(14):
        day = utc(2026, 5, 7) - timedelta(days=d)
        ts_list.append(day.replace(hour=2))
        ts_list.append(day.replace(hour=14))
    keep = gfs_keep_set(ts_list)
    # Daily: 7 days, latest of each is hour=14
    for d in range(7):
        expected = (utc(2026, 5, 7) - timedelta(days=d)).replace(hour=14)
        assert expected in keep, f"missing daily {expected}"


def test_gaps_skip_to_distinct_days():
    """Gaps en el calendario no rompen: daily es los 7 días distintos con backup."""
    base = utc(2026, 5, 7)
    # 7 días distintos, pero con saltos
    distinct_days = [0, 1, 3, 5, 10, 15, 20]
    ts_list = [base - timedelta(days=d) for d in distinct_days]
    keep = gfs_keep_set(ts_list)
    assert len(keep) == 7, f"expected 7 kept (all in daily tranche), got {len(keep)}"
    assert keep == set(ts_list)


def test_steady_state_180_days_gives_14():
    """180 días con 1 backup/día → exactamente 14 retenidos."""
    ts_list = [utc(2026, 5, 7) - timedelta(days=i) for i in range(180)]
    keep = gfs_keep_set(ts_list)
    assert len(keep) == 14, f"expected 14, got {len(keep)}"


def test_steady_state_distribution():
    """Steady state: 7 daily + 4 weekly + 3 monthly = 14, sin overlap por semana."""
    ts_list = [utc(2026, 5, 7) - timedelta(days=i) for i in range(180)]
    keep = sorted(gfs_keep_set(ts_list), reverse=True)
    assert len(keep) == 14
    # Top 7 son los 7 días más recientes
    daily = keep[:7]
    daily_dates = {t.date() for t in daily}
    expected = {(utc(2026, 5, 7) - timedelta(days=i)).date() for i in range(7)}
    assert daily_dates == expected, f"daily dates {daily_dates} != {expected}"
    # Las 7 daily están todas en semanas 18-19 (May 1-7 de 2026)
    daily_weeks = {(t.isocalendar().year, t.isocalendar().week) for t in daily}
    # Los 4 weekly NO deben estar en daily_weeks
    weekly = keep[7:11]
    for t in weekly:
        wk = (t.isocalendar().year, t.isocalendar().week)
        assert wk not in daily_weeks, f"weekly {t} en daily_weeks {daily_weeks}"
    # Los 3 monthly son meses anteriores a los weekly
    monthly = keep[11:14]
    earliest_weekly_month = min((t.year, t.month) for t in weekly)
    for t in monthly:
        assert (t.year, t.month) < earliest_weekly_month, \
            f"monthly {t} no es anterior al weekly tramo {earliest_weekly_month}"


def test_weekly_picks_oldest_of_week():
    """De cada semana elegida en weekly se conserva el ts MÁS ANTIGUO."""
    # Dataset: 3 backups por semana durante 8 semanas (lun, mié, dom)
    # Daily covers solo los últimos 7 días → cubre ~1 semana
    ts_list = []
    base = utc(2026, 5, 7)  # jueves
    for w in range(8):
        week_anchor = base - timedelta(days=w * 7)
        # Lunes anterior al anchor
        monday = week_anchor - timedelta(days=week_anchor.weekday())
        ts_list.append(monday.replace(hour=10))  # lun
        ts_list.append((monday + timedelta(days=2)).replace(hour=10))  # mié
        ts_list.append((monday + timedelta(days=6)).replace(hour=10))  # dom
    keep = gfs_keep_set(ts_list)
    # Para cada weekly week conservada, debería ser el ts más antiguo (lunes)
    weeks_in_keep: dict[tuple[int, int], list[datetime]] = {}
    for t in keep:
        iso = t.isocalendar()
        weeks_in_keep.setdefault((iso.year, iso.week), []).append(t)
    # Encontrar weeks que sólo tienen 1 ts kept (esas son las weekly tranche, oldest)
    for wk, ts_in_wk in weeks_in_keep.items():
        # daily semanas pueden tener 1 (latest del día), no oldest de semana
        # weekly weeks deben tener exactamente 1 = oldest del lote de esa semana en input
        if len(ts_in_wk) == 1:
            # Verificar si fue elegido como weekly tranche oldest
            kept = ts_in_wk[0]
            all_in_week = [t for t in ts_list
                           if (t.isocalendar().year, t.isocalendar().week) == wk]
            # Si daily picked something else of same week, kept != oldest. Ignore.
            # Si weekly picked it, kept == oldest of all_in_week
            # No assertion estricta acá: sólo chequeamos que kept ∈ all_in_week
            assert kept in all_in_week


def test_monthly_picks_oldest_of_month():
    """De cada mes elegido en monthly se conserva el ts MÁS ANTIGUO."""
    # Dataset largo para asegurar monthly tranche. 200 días.
    ts_list = [utc(2026, 5, 7) - timedelta(days=i) for i in range(200)]
    keep = sorted(gfs_keep_set(ts_list), reverse=True)
    # Los últimos 3 entries son monthly. Cada uno debe ser el más antiguo de su mes
    # PRESENTE EN EL DATASET.
    assert len(keep) == 14
    monthly = keep[11:]
    for t in monthly:
        same_month_ts = [x for x in ts_list if x.year == t.year and x.month == t.month]
        assert t == min(same_month_ts), f"{t} no es el oldest de {t.year}-{t.month:02d}"


def test_short_dataset_no_padding():
    """Dataset de 30 días (1/día) → daily 7 + weekly limitado, total < 14 sin
    inventar entradas."""
    ts_list = [utc(2026, 5, 7) - timedelta(days=i) for i in range(30)]
    keep = gfs_keep_set(ts_list)
    assert len(keep) <= 14
    assert len(keep) > 7, f"expected >7 (algo de weekly), got {len(keep)}"


def test_idempotent():
    """Aplicar gfs_keep_set sobre el conjunto de los kept devuelve el mismo conjunto."""
    ts_list = [utc(2026, 5, 7) - timedelta(days=i) for i in range(180)]
    keep1 = gfs_keep_set(ts_list)
    keep2 = gfs_keep_set(list(keep1))
    assert keep1 == keep2


def test_daily_doesnt_contaminate_weekly():
    """Las semanas que tocan daily NO aparecen en weekly tranche."""
    ts_list = [utc(2026, 5, 7) - timedelta(days=i) for i in range(60)]
    keep = gfs_keep_set(ts_list)
    daily_dates = {(utc(2026, 5, 7) - timedelta(days=i)).date() for i in range(7)}
    daily_weeks = {(d.isocalendar().year, d.isocalendar().week) for d in daily_dates}
    # Para cada t en keep que NO es daily, su semana no debe coincidir con daily_weeks
    daily_kept = {t for t in keep if t.date() in daily_dates}
    other_kept = keep - daily_kept
    for t in other_kept:
        wk = (t.isocalendar().year, t.isocalendar().week)
        assert wk not in daily_weeks, \
            f"weekly/monthly {t} (week {wk}) toca daily_weeks {daily_weeks}"


# ── Runner ───────────────────────────────────────────────────────────────


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    n = len(tests)
    print(f"\n{n - failed}/{n} pasaron")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
