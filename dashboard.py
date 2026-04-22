#!/usr/bin/env python3
"""
dashboard.py — Genera dashboard HTML desde p2p_normalized.db.

Uso:
    python3 dashboard.py                           # defaults
    python3 dashboard.py --db mi_base.db           # DB custom
    python3 dashboard.py --output dashboard.html   # output custom
    python3 dashboard.py --csv                     # también exporta CSV horario

Produce un .html autocontenido que se abre en cualquier navegador.
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

DEFAULT_DB = Path("p2p_normalized.db")
DEFAULT_OUTPUT = Path("index.html")
BCB_RATE = 6.96
BCB_REF_FILE = Path("bcb_referencial.json")


def load_bcb_ref(first_date: str | None = None) -> dict:
    """Lee bcb_referencial.json (array de {fecha,compra,venta}). Soporta formato
    viejo (dict) como fallback. Devuelve dict con latest + history.

    first_date (YYYY-MM-DD): si se pasa, filtra el histórico para que solo incluya
    entradas con fecha >= first_date. La última entrada siempre se conserva para
    el KPI aunque esté fuera de rango."""
    out = {'bcb_ref_compra': None, 'bcb_ref_venta': None,
           'bcb_ref_fecha': None, 'bcb_ref_history': []}
    try:
        if BCB_REF_FILE.exists():
            data = json.loads(BCB_REF_FILE.read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('fecha_publicacion'):
                # Formato viejo
                data = [{'fecha': data['fecha_publicacion'],
                         'compra': data.get('compra'),
                         'venta': data.get('venta')}]
            if isinstance(data, list) and data:
                full_hist = sorted(
                    [h for h in data if h.get('fecha')],
                    key=lambda h: h['fecha'])
                latest = full_hist[-1]
                out['bcb_ref_compra'] = latest.get('compra')
                out['bcb_ref_venta'] = latest.get('venta')
                out['bcb_ref_fecha'] = latest.get('fecha')
                # Filtrar para el gráfico (serie temporal dentro del rango de snapshots)
                if first_date:
                    out['bcb_ref_history'] = [h for h in full_hist if h['fecha'] >= first_date]
                else:
                    out['bcb_ref_history'] = full_hist
    except Exception:
        pass
    return out

# ── Cálculo de VWAP ────────────────────────────────────────────────────────

def vwap_by_depth(prices_and_sizes, pct):
    """prices_and_sizes: lista de (price, surplus) ya ordenada por 'mejor' primero."""
    if not prices_and_sizes:
        return None
    total = sum(s for _, s in prices_and_sizes)
    if total == 0:
        return None
    budget = total * pct
    acc = wp = 0.0
    for price, size in prices_and_sizes:
        take = min(size, budget - acc)
        if take <= 0:
            break
        wp += price * take
        acc += take
    return round(wp / acc, 6) if acc > 0 else None


# ── Procesamiento ──────────────────────────────────────────────────────────

def process_data(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    timestamps = [r[0] for r in conn.execute(
        "SELECT DISTINCT snapshot_ts_utc FROM ads ORDER BY snapshot_ts_utc"
    ).fetchall()]
    ts_data = []
    decile_data = {}
    for ts in timestamps:
        rows = conn.execute(
            "SELECT side, price, surplus_usdt, advertiser_id FROM ads WHERE snapshot_ts_utc=?",
            (ts,)).fetchall()
        buy_raw = [(r['price'], r['surplus_usdt'], r['advertiser_id']) for r in rows if r['side'] == 'BUY']
        sell_raw = [(r['price'], r['surplus_usdt'], r['advertiser_id']) for r in rows if r['side'] == 'SELL']
        buy_sorted = sorted(buy_raw, key=lambda x: x[0])
        sell_sorted = sorted(sell_raw, key=lambda x: -x[0])
        buy_ps = [(p, s) for p, s, _ in buy_sorted]
        sell_ps = [(p, s) for p, s, _ in sell_sorted]
        buy_depth = sum(s for _, s in buy_ps)
        sell_depth = sum(s for _, s in sell_ps)
        d = {
            'ts': ts, 'buy_count': len(buy_raw), 'sell_count': len(sell_raw),
            'buy_depth': round(buy_depth), 'sell_depth': round(sell_depth),
            'depth_ratio': round(sell_depth / buy_depth, 2) if buy_depth > 0 else None,
        }
        for pl, pv in [('5', 0.05), ('10', 0.10), ('25', 0.25), ('50', 0.50)]:
            vb = vwap_by_depth(buy_ps, pv)
            vs = vwap_by_depth(sell_ps, pv)
            d[f'vb{pl}'] = vb
            d[f'vs{pl}'] = vs
            d[f'sp{pl}'] = round(vb - vs, 4) if (vb and vs) else None
        for side_name, side_data, depth in [('buy', buy_raw, buy_depth), ('sell', sell_raw, sell_depth)]:
            merchants = {}
            for _, surplus, adv_id in side_data:
                merchants[adv_id] = merchants.get(adv_id, 0) + surplus
            top5 = sum(sorted(merchants.values(), reverse=True)[:5])
            d[f't5{side_name}'] = round(top5 / depth * 100, 1) if depth > 0 else 0
        ts_data.append(d)
        decile_data[ts] = {
            'BUY': [vwap_by_depth(buy_ps, i * 0.1) for i in range(1, 11)],
            'SELL': [vwap_by_depth(sell_ps, i * 0.1) for i in range(1, 11)],
        }
    def _group_last(data, key_fn):
        groups = {}
        for d in data:
            groups[key_fn(d['ts'])] = d
        return list(groups.values())
    hourly = _group_last(ts_data, lambda ts: ts[:13])
    daily = _group_last(ts_data, lambda ts: ts[:10])
    last_ts = timestamps[-1]
    bank_rows = conn.execute("SELECT banks, surplus_usdt FROM ads WHERE snapshot_ts_utc=?", (last_ts,)).fetchall()
    bank_stats = {}
    total_depth_last = 0
    for r in bank_rows:
        banks = json.loads(r['banks']) if r['banks'] else []
        total_depth_last += r['surplus_usdt']
        for b in banks:
            if b == 'BANK': continue
            if b not in bank_stats: bank_stats[b] = {'count': 0, 'depth': 0}
            bank_stats[b]['count'] += 1
            bank_stats[b]['depth'] += r['surplus_usdt']
    bank_list = [
        {'name': b.replace('Banco', '').replace('De', 'de '), 'count': s['count'],
         'depth': round(s['depth']), 'depth_pct': round(s['depth'] / total_depth_last * 100, 1)}
        for b, s in sorted(bank_stats.items(), key=lambda x: -x[1]['depth'])
    ]

    # ── Panel 1: Top merchants (last snapshot of each view) ──
    view_last_ts = set()
    if ts_data:    view_last_ts.add(ts_data[-1]['ts'])
    if hourly:     view_last_ts.add(hourly[-1]['ts'])
    if daily:      view_last_ts.add(daily[-1]['ts'])
    top_merchants = {}
    for view_ts in view_last_ts:
        rows = conn.execute("""
            SELECT side, advertiser_nick, advertiser_id, price, surplus_usdt,
                   n_banks, month_order_count
            FROM ads WHERE snapshot_ts_utc=?
        """, (view_ts,)).fetchall()
        agg = {}
        for r in rows:
            key = (r['side'], r['advertiser_id'])
            if key not in agg:
                agg[key] = {'nick': r['advertiser_nick'] or '(sin nick)',
                            'depth': 0, 'price_w': 0,
                            'n_banks': r['n_banks'] or 0,
                            'month_order_count': r['month_order_count'] or 0}
            agg[key]['depth'] += r['surplus_usdt'] or 0
            agg[key]['price_w'] += (r['price'] or 0) * (r['surplus_usdt'] or 0)
        totals = {'BUY': 0, 'SELL': 0}
        for (side, _), v in agg.items():
            totals[side] += v['depth']
        result = {'BUY': [], 'SELL': []}
        for side in ('BUY', 'SELL'):
            entries = sorted(
                [v for (s, _), v in agg.items() if s == side],
                key=lambda e: -e['depth']
            )[:10]
            total = totals[side] or 1
            result[side] = [{
                'nick': e['nick'],
                'depth': round(e['depth']),
                'pct': round(e['depth'] / total * 100, 1),
                'vwap': round(e['price_w'] / e['depth'], 4) if e['depth'] > 0 else None,
                'n_banks': e['n_banks'],
                'month_order_count': e['month_order_count'],
            } for e in entries]
        top_merchants[view_ts] = result

    # ── Panel 2: Volatilidad intradiaria (daily) ──
    vol_by_day = defaultdict(lambda: {'vb10': [], 'vs10': []})
    for d in ts_data:
        day = d['ts'][:10]
        if d.get('vb10') is not None: vol_by_day[day]['vb10'].append(d['vb10'])
        if d.get('vs10') is not None: vol_by_day[day]['vs10'].append(d['vs10'])
    volatility_daily = [
        {'date': day,
         'buy_range': round(max(v['vb10']) - min(v['vb10']), 4) if v['vb10'] else None,
         'sell_range': round(max(v['vs10']) - min(v['vs10']), 4) if v['vs10'] else None}
        for day, v in sorted(vol_by_day.items())
    ]

    # ── Panel 3: Merchants activos / flow ──
    all_ts_list = [d['ts'] for d in ts_data]
    ids_by_ts = defaultdict(lambda: {'BUY': set(), 'SELL': set()})
    if all_ts_list:
        rows = conn.execute(
            "SELECT snapshot_ts_utc, side, advertiser_id FROM ads"
        ).fetchall()
        for r in rows:
            ids_by_ts[r['snapshot_ts_utc']][r['side']].add(r['advertiser_id'])

    def compute_flow(ts_list):
        out = []
        prev = None
        for ts in ts_list:
            cur = ids_by_ts.get(ts, {'BUY': set(), 'SELL': set()})
            entry = {'ts': ts, 'n_buy': len(cur['BUY']), 'n_sell': len(cur['SELL'])}
            if prev is None:
                entry.update({'new_buy': 0, 'gone_buy': 0, 'new_sell': 0, 'gone_sell': 0})
            else:
                entry.update({
                    'new_buy':  len(cur['BUY']  - prev['BUY']),
                    'gone_buy': len(prev['BUY'] - cur['BUY']),
                    'new_sell':  len(cur['SELL']  - prev['SELL']),
                    'gone_sell': len(prev['SELL'] - cur['SELL']),
                })
            out.append(entry)
            prev = cur
        return out

    merchant_flow = {
        'all':    compute_flow(all_ts_list),
        'hourly': compute_flow([d['ts'] for d in hourly]),
        'daily':  compute_flow([d['ts'] for d in daily]),
    }

    # ── Panel 4: Heatmap por hora del día (Bolivia UTC-4) ──
    bolivia = timezone(timedelta(hours=-4))
    metrics_def = [
        ('buy_depth',  'Profundidad BUY'),
        ('sell_depth', 'Profundidad SELL'),
        ('sp10',       'Spread 10%'),
        ('n_ads',      'Anuncios'),
        ('vb10',       'VWAP 10% BUY'),
        ('vs10',       'VWAP 10% SELL'),
    ]
    hm_sums = {k: [[0, 0] for _ in range(24)] for k, _ in metrics_def}
    for d in ts_data:
        try:
            dt = datetime.fromisoformat(d['ts'].replace('Z', '+00:00')).astimezone(bolivia)
            h = dt.hour
        except Exception:
            continue
        for key, _ in metrics_def:
            val = (d['buy_count'] + d['sell_count']) if key == 'n_ads' else d.get(key)
            if val is None:
                continue
            hm_sums[key][h][0] += val
            hm_sums[key][h][1] += 1
    heatmap_data = {
        'hours': list(range(24)),
        'metrics': [
            {'key': key, 'label': label, 'values': [
                round(hm_sums[key][h][0] / hm_sums[key][h][1], 4)
                if hm_sums[key][h][1] > 0 else None
                for h in range(24)
            ]}
            for key, label in metrics_def
        ]
    }

    conn.close()
    return {
        'ts': ts_data, 'hourly': hourly, 'daily': daily,
        'deciles': decile_data, 'banks': bank_list,
        'top_merchants': top_merchants,
        'volatility_daily': volatility_daily,
        'merchant_flow': merchant_flow,
        'heatmap': heatmap_data,
        'meta': {
            'total_snapshots': len(timestamps),
            'total_ads': sum(d['buy_count'] + d['sell_count'] for d in ts_data),
            'first_ts': timestamps[0], 'last_ts': timestamps[-1], 'bcb_rate': BCB_RATE,
            **load_bcb_ref(first_date=timestamps[0][:10] if timestamps else None),
        }
    }


# ── CSV horario ────────────────────────────────────────────────────────────

def export_hourly_csv(data: dict, csv_path: Path):
    import csv
    rows = []
    for d in data['ts']:
        rows.append({
            'timestamp_utc': d['ts'], 'buy_count': d['buy_count'], 'sell_count': d['sell_count'],
            'buy_depth_usdt': d['buy_depth'], 'sell_depth_usdt': d['sell_depth'],
            'depth_ratio': d['depth_ratio'],
            'vwap_buy_5': d.get('vb5'), 'vwap_buy_10': d.get('vb10'),
            'vwap_buy_25': d.get('vb25'), 'vwap_buy_50': d.get('vb50'),
            'vwap_sell_5': d.get('vs5'), 'vwap_sell_10': d.get('vs10'),
            'vwap_sell_25': d.get('vs25'), 'vwap_sell_50': d.get('vs50'),
            'spread_5': d.get('sp5'), 'spread_10': d.get('sp10'),
            'spread_25': d.get('sp25'), 'spread_50': d.get('sp50'),
            'top5_buy_pct': d.get('t5buy'), 'top5_sell_pct': d.get('t5sell'),
        })
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  CSV horario: {csv_path} ({len(rows)} filas)")


# ── HTML template ──────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>P2P USDT/BOB — Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.35.0.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg-primary:#f7f5f0;--bg-secondary:#fff;--bg-tertiary:#eeece6;--border-color:#ddd9d0;--text-primary:#1a1a1a;--text-secondary:#5c5c5c;--text-muted:#9a9a9a;--green:#2d7a4f;--green-muted:rgba(45,122,79,.10);--orange:#b35c1e;--orange-muted:rgba(179,92,30,.10);--blue-accent:#3b6fb5;--kpi-value-size:28px}
*,*::before,*::after{transition:background-color .3s,color .3s,border-color .3s}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg-primary);color:var(--text-primary);font-family:'Outfit',sans-serif;min-height:100vh}

/* ── Theme bar ── */
.theme-bar{display:flex;align-items:center;gap:4px;padding:4px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-secondary);margin-left:auto}
.theme-btn{font-family:'Outfit',sans-serif;font-size:11px;font-weight:500;padding:5px 12px;border:none;border-radius:5px;cursor:pointer;background:transparent;color:var(--text-muted);transition:all .2s;white-space:nowrap}
.theme-btn:hover{background:var(--bg-tertiary);color:var(--text-primary)}
.theme-btn.active{background:var(--bg-tertiary);color:var(--text-primary);font-weight:600}
.theme-bar-sep{width:1px;height:20px;background:var(--border-color);margin:0 2px}

/* ── Dropdown (Otros / Editar) ── */
.tb-dropdown-wrap{position:relative}
.tb-dropdown{position:absolute;top:calc(100% + 8px);right:0;min-width:240px;padding:12px;background:var(--bg-secondary);border:1px solid var(--border-color);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.2);display:none;z-index:1001}
.tb-dropdown.open{display:block}
.tb-dd-title{font-family:'Outfit',sans-serif;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--text-muted);margin-bottom:8px}
.tb-dd-item{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:4px;cursor:pointer;font-family:'Outfit',sans-serif;font-size:12px;color:var(--text-primary);transition:background .15s}
.tb-dd-item:hover{background:var(--bg-tertiary)}
.tb-dd-item.is-active{font-weight:600}
.tb-dd-item .dd-dot{width:12px;height:12px;border-radius:50%;flex-shrink:0}
.tb-dd-item .dd-del{margin-left:auto;font-size:14px;color:var(--text-muted);cursor:pointer;padding:0 4px;background:none;border:none;font-family:inherit}
.tb-dd-item .dd-del:hover{color:var(--orange)}
.tb-dd-divider{height:1px;background:var(--border-color);margin:8px 0}
.tb-dd-action{display:flex;align-items:center;gap:6px;padding:6px 8px;border-radius:4px;cursor:pointer;font-family:'Outfit',sans-serif;font-size:12px;color:var(--text-secondary);transition:all .15s}
.tb-dd-action:hover{background:var(--bg-tertiary);color:var(--text-primary)}
.tb-dd-empty{font-size:11px;color:var(--text-muted);padding:4px 8px;font-style:italic}
.tb-dd-note{font-size:10px;color:var(--text-muted);padding:4px 8px;margin-top:4px}

/* ── Edit panel ── */
.edit-panel{min-width:260px;padding:14px}
.edit-panel .cp-row{display:flex;align-items:center;gap:8px;margin-bottom:5px}
.edit-panel label{font-family:'Outfit',sans-serif;font-size:11px;color:var(--text-muted);width:48px;text-align:right}
.edit-panel input[type="color"]{width:32px;height:24px;border:1px solid var(--border-color);border-radius:4px;cursor:pointer;background:transparent;padding:0;-webkit-appearance:none}
.edit-panel input[type="color"]::-webkit-color-swatch-wrapper{padding:2px}
.edit-panel input[type="color"]::-webkit-color-swatch{border-radius:2px;border:none}
.edit-panel .ep-buttons{display:flex;gap:6px;margin-top:8px}
.edit-panel button{padding:5px 10px;font-family:'Outfit',sans-serif;font-size:11px;font-weight:500;border:1px solid var(--border-color);border-radius:4px;background:transparent;color:var(--text-secondary);cursor:pointer;transition:background .15s;flex:1}
.edit-panel button:hover{background:var(--bg-tertiary)}

/* ── Logo ── */
.logo{display:flex;align-items:center;gap:10px;flex-shrink:0}
.logo-ddr{font-family:'Outfit',sans-serif;font-size:28px;font-weight:700;color:var(--blue-accent);letter-spacing:.08em}
.logo-separator{width:1px;height:32px;background:var(--text-muted)}
.logo-text{font-family:'Outfit',sans-serif;font-size:11px;font-weight:400;color:var(--text-secondary);letter-spacing:.15em;text-transform:uppercase;line-height:1.3}

/* ── Header ── */
.header{background:var(--bg-secondary);padding:28px 48px 24px;border-bottom:1px solid var(--border-color)}
.header-top{display:flex;justify-content:space-between;align-items:flex-start;gap:24px}
.header-left{display:flex;align-items:center;gap:24px}
.header h1{font-family:'Outfit',sans-serif;font-size:22px;font-weight:600;color:var(--text-primary);letter-spacing:-.02em}
.header .subtitle{font-size:13px;color:var(--text-muted);margin-top:3px;font-weight:400}
.header .meta{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--text-muted);text-align:right;line-height:1.7;flex-shrink:0}
.header .meta strong{color:var(--text-secondary);font-weight:500}

/* ── KPIs ── */
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:0;background:var(--bg-secondary);border-bottom:1px solid var(--border-color)}
.kpi{padding:18px 24px;border-right:1px solid var(--border-color)}
.kpi:last-child{border-right:none}
.kpi .label{font-family:'Outfit',sans-serif;font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:.08em;color:var(--text-muted);margin-bottom:8px}
.kpi .value{font-family:'IBM Plex Mono',monospace;font-size:var(--kpi-value-size);font-weight:600;color:var(--text-primary);letter-spacing:-.02em}
.kpi .sub{font-size:11px;color:var(--text-muted);margin-top:3px}
.kpi .value.buy{color:var(--green)}.kpi .value.sell{color:var(--orange)}.kpi .value.spread{color:var(--blue-accent)}

/* ── Content ── */
.content{padding:20px 48px 48px;max-width:1440px;margin:0 auto}
.toolbar{display:flex;align-items:center;gap:12px;margin-bottom:16px}
.view-toggle{display:flex;gap:0}
.toggle-btn{padding:7px 18px;font-family:'Outfit',sans-serif;font-size:12px;font-weight:500;border:1px solid var(--border-color);background:transparent;color:var(--text-secondary);cursor:pointer;margin-right:-1px;transition:all .15s}
.toggle-btn:first-child{border-radius:4px 0 0 4px}
.toggle-btn:last-child{border-radius:0 4px 4px 0;margin-right:0}
.toggle-btn:hover{background:var(--bg-tertiary);color:var(--text-primary)}
.toggle-btn.active{background:var(--blue-accent);color:#fff;border-color:var(--blue-accent)}

/* ── Sections ── */
.section{background:var(--bg-secondary);border:1px solid var(--border-color);border-radius:6px;margin-bottom:16px;overflow:hidden}
.section-header{padding:16px 20px 12px;border-bottom:1px solid var(--border-color)}
.section-header h2{font-family:'Outfit',sans-serif;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;color:var(--text-secondary)}
.section-header p{font-size:12px;font-weight:400;color:var(--text-muted);margin-top:3px;line-height:1.4}
.section-body{padding:16px 20px 20px}

/* ── Bank table ── */
.bank-table{width:100%;border-collapse:collapse}
.bank-table th{text-align:left;font-family:'Outfit',sans-serif;font-size:10px;font-weight:500;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);padding:10px 14px;border-bottom:1px solid var(--border-color)}
.bank-table td{padding:8px 14px;border-bottom:1px solid var(--border-color);font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--text-secondary)}
.bank-table td:first-child{font-family:'Outfit',sans-serif;font-weight:500;font-size:12px;color:var(--text-primary)}
.bank-table tr:hover td{background:var(--bg-tertiary)}
.bar-cell{position:relative;z-index:1}
.bar-fill{position:absolute;left:0;top:2px;bottom:2px;border-radius:2px;z-index:-1}

/* ── Merchants table ── */
.merchants-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:900px){.merchants-grid{grid-template-columns:1fr}}
.merchants-side h3{font-family:'Outfit',sans-serif;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--text-muted);margin-bottom:6px}
.merchants-table{width:100%;border-collapse:collapse;font-size:11px}
.merchants-table th{text-align:left;font-family:'Outfit',sans-serif;font-size:9.5px;font-weight:500;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);padding:6px 8px;border-bottom:1px solid var(--border-color);white-space:nowrap}
.merchants-table td{padding:5px 8px;border-bottom:1px solid var(--border-color);font-family:'IBM Plex Mono',monospace;color:var(--text-secondary);white-space:nowrap}
.merchants-table td.nick{font-family:'Outfit',sans-serif;color:var(--text-primary);font-weight:500;max-width:140px;overflow:hidden;text-overflow:ellipsis}
.merchants-table td.num{text-align:right}
.merchants-table tr:hover td{background:var(--bg-tertiary)}
.view-hint{padding:36px 16px;text-align:center;color:var(--text-muted);font-size:12px;font-style:italic}

/* ── Panel grid ── */
.panel-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
.panel-grid .section{margin-bottom:0}
.panel-grid .section.full-width{grid-column:1/-1}
.section .section-header{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.section .sh-left{flex:1;min-width:0}
.section .sh-controls{display:flex;gap:4px;flex-shrink:0;margin-top:2px}
.sh-ctrl-btn{width:24px;height:24px;border:none;border-radius:4px;background:transparent;color:var(--text-muted);cursor:pointer;font-size:13px;display:flex;align-items:center;justify-content:center;transition:all .15s;padding:0}
.sh-ctrl-btn:hover{background:var(--bg-tertiary);color:var(--text-primary)}
.sh-ctrl-btn.drag-handle{cursor:grab}
.sh-ctrl-btn.drag-handle:active{cursor:grabbing}
.section.drag-over{outline:2px dashed var(--blue-accent);outline-offset:-2px}
.section.dragging{opacity:.4}

/* ── Footer ── */
.footer{padding:16px 48px;font-family:'IBM Plex Mono',monospace;font-size:9px;color:var(--text-muted);text-align:center;border-top:1px solid var(--border-color)}
.footer strong{color:var(--text-secondary);font-weight:600}

@media(max-width:900px){.header{padding:20px 24px 18px}.header-left{flex-direction:column;align-items:flex-start;gap:12px}.content{padding:16px 24px 32px}.panel-grid{grid-template-columns:1fr}.panel-grid .section.full-width{grid-column:1}.footer{padding:16px 24px}}
@media(max-width:768px){.theme-btn .btn-full{display:none}.theme-btn .btn-short{display:inline}}
@media(min-width:769px){.theme-btn .btn-short{display:none}}
</style></head>
<body>

<!-- Header -->
<div class="header"><div class="header-top">
  <div class="header-left">
    <div class="logo"><span class="logo-ddr">DDR</span><span class="logo-separator"></span><span class="logo-text">CAPITAL<br>PARTNERS</span></div>
    <div><h1>Mercado P2P USDT/BOB</h1><div class="subtitle">Libro de anuncios — Binance P2P Bolivia</div></div>
  </div>
  <div class="meta" id="headerMeta"></div>
</div></div>

<div class="kpi-row" id="kpis"></div>

<div class="content">
  <div class="toolbar">
    <div class="view-toggle">
      <button class="toggle-btn active" data-view="hourly">Por hora</button>
      <button class="toggle-btn" data-view="daily">Por d&iacute;a</button>
      <button class="toggle-btn" data-view="all">Cada snapshot</button>
    </div>
    <div class="theme-bar" id="themeBar">
      <button class="theme-btn active" data-theme="paper"><span class="btn-full">Claro</span><span class="btn-short">C</span></button>
      <button class="theme-btn" data-theme="claude"><span class="btn-full">Beige</span><span class="btn-short">B</span></button>
      <button class="theme-btn" data-theme="slate"><span class="btn-full">Oscuro</span><span class="btn-short">O</span></button>
      <div class="theme-bar-sep"></div>
      <div class="tb-dropdown-wrap" id="othersWrap">
        <button class="theme-btn" id="othersBtn"><span class="btn-full">Otros &#9662;</span><span class="btn-short">&#8230;</span></button>
        <div class="tb-dropdown" id="othersDd">
          <div class="tb-dd-title">M&aacute;s temas</div>
          <div class="tb-dd-item" data-id="ink"><div class="dd-dot" style="background:#000"></div><span>Negro</span></div>
          <div class="tb-dd-divider"></div>
          <div class="tb-dd-title">Mis temas</div>
          <div id="customList"></div>
          <div class="tb-dd-divider"></div>
          <div class="tb-dd-action" id="importBtn">&#128203; Importar tema (JSON)</div>
          <div class="tb-dd-note">M&aacute;ximo 5 temas</div>
        </div>
      </div>
      <div class="tb-dropdown-wrap" id="editWrap">
        <button class="theme-btn" id="editBtn"><span class="btn-full">Editar &#9881;</span><span class="btn-short">&#9881;</span></button>
        <div class="tb-dropdown edit-panel" id="editDd">
          <div class="cp-row"><label>Fondo</label><input type="color" id="cp-bg-primary" value="#f7f5f0"></div>
          <div class="cp-row"><label>Panel</label><input type="color" id="cp-bg-secondary" value="#ffffff"></div>
          <div class="cp-row"><label>Borde</label><input type="color" id="cp-border-color" value="#ddd9d0"></div>
          <div class="cp-row"><label>Texto</label><input type="color" id="cp-text-primary" value="#1a1a1a"></div>
          <div class="cp-row"><label>Label</label><input type="color" id="cp-text-secondary" value="#5c5c5c"></div>
          <div class="cp-row"><label>Compra</label><input type="color" id="cp-green" value="#2d7a4f"></div>
          <div class="cp-row"><label>Venta</label><input type="color" id="cp-orange" value="#b35c1e"></div>
          <div class="cp-row"><label>Acento</label><input type="color" id="cp-blue-accent" value="#3b6fb5"></div>
          <div class="ep-buttons">
            <button id="cpSaveAs">Guardar como&hellip;</button>
            <button id="cpExport">Export JSON</button>
            <button id="cpReset">Reset</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div class="panel-grid" id="panelGrid">
    <div class="section full-width" data-panel="vwap" draggable="true"><div class="section-header"><div class="sh-left"><h2>Precio VWAP por nivel de profundidad</h2><p>Bandas: deterioro a mayor profundidad (5%&rarr;50%). En la leyenda: BCB 6.96 (oficial) y BCB Ref Compra/Venta (referencial BCB).</p></div><div class="sh-controls"><button class="sh-ctrl-btn size-toggle" title="Alternar ancho">&#11036;</button><button class="sh-ctrl-btn drag-handle" title="Mover">&#10303;</button></div></div><div class="section-body"><div id="chartVwap"></div></div></div>
    <div class="section" data-panel="spread" draggable="true"><div class="section-header"><div class="sh-left"><h2>Spread efectivo</h2><p>Diferencia VWAP BUY - SELL por profundidad.</p></div><div class="sh-controls"><button class="sh-ctrl-btn size-toggle" title="Alternar ancho">&#11036;</button><button class="sh-ctrl-btn drag-handle" title="Mover">&#10303;</button></div></div><div class="section-body"><div id="chartSpread"></div></div></div>
    <div class="section" data-panel="depth" draggable="true"><div class="section-header"><div class="sh-left"><h2>Profundidad por lado</h2><p>USDT totales en anuncios activos.</p></div><div class="sh-controls"><button class="sh-ctrl-btn size-toggle" title="Alternar ancho">&#11036;</button><button class="sh-ctrl-btn drag-handle" title="Mover">&#10303;</button></div></div><div class="section-body"><div id="chartDepth"></div></div></div>
    <div class="section" data-panel="decile" draggable="true"><div class="section-header"><div class="sh-left"><h2>Curva de precio por decil</h2><p>VWAP acumulado 10%-100%.</p></div><div class="sh-controls"><button class="sh-ctrl-btn size-toggle" title="Alternar ancho">&#11036;</button><button class="sh-ctrl-btn drag-handle" title="Mover">&#10303;</button></div></div><div class="section-body"><div id="chartDecile"></div></div></div>
    <div class="section" data-panel="ratio" draggable="true"><div class="section-header"><div class="sh-left"><h2>Ratio SELL / BUY</h2><p>&gt;1 = m&aacute;s oferta que demanda.</p></div><div class="sh-controls"><button class="sh-ctrl-btn size-toggle" title="Alternar ancho">&#11036;</button><button class="sh-ctrl-btn drag-handle" title="Mover">&#10303;</button></div></div><div class="section-body"><div id="chartRatio"></div></div></div>
    <div class="section" data-panel="conc" draggable="true"><div class="section-header"><div class="sh-left"><h2>Concentraci&oacute;n Top 5</h2><p>% de profundidad de los 5 merchants m&aacute;s grandes.</p></div><div class="sh-controls"><button class="sh-ctrl-btn size-toggle" title="Alternar ancho">&#11036;</button><button class="sh-ctrl-btn drag-handle" title="Mover">&#10303;</button></div></div><div class="section-body"><div id="chartConc"></div></div></div>
    <div class="section" data-panel="bank" draggable="true"><div class="section-header"><div class="sh-left"><h2>Cobertura por banco</h2><p>Anuncios y profundidad por m&eacute;todo de pago.</p></div><div class="sh-controls"><button class="sh-ctrl-btn size-toggle" title="Alternar ancho">&#11036;</button><button class="sh-ctrl-btn drag-handle" title="Mover">&#10303;</button></div></div><div class="section-body"><div id="bankTable"></div></div></div>
    <div class="section full-width" data-panel="merchants" draggable="true"><div class="section-header"><div class="sh-left"><h2>Merchants principales</h2><p>Top 10 merchants por profundidad en el &uacute;ltimo snapshot de la vista activa.</p></div><div class="sh-controls"><button class="sh-ctrl-btn size-toggle" title="Alternar ancho">&#11036;</button><button class="sh-ctrl-btn drag-handle" title="Mover">&#10303;</button></div></div><div class="section-body"><div id="topMerchants"></div></div></div>
    <div class="section" data-panel="volatility" draggable="true"><div class="section-header"><div class="sh-left"><h2>Volatilidad intradiaria</h2><p>Rango (max-min) del VWAP 10% por d&iacute;a. Solo en vista &quot;Por d&iacute;a&quot;.</p></div><div class="sh-controls"><button class="sh-ctrl-btn size-toggle" title="Alternar ancho">&#11036;</button><button class="sh-ctrl-btn drag-handle" title="Mover">&#10303;</button></div></div><div class="section-body"><div id="chartVolatility"></div></div></div>
    <div class="section" data-panel="flow" draggable="true"><div class="section-header"><div class="sh-left"><h2>Merchants activos</h2><p>Merchants &uacute;nicos por side. Barras: nuevos (+) y desaparecidos (-) vs punto anterior.</p></div><div class="sh-controls"><button class="sh-ctrl-btn size-toggle" title="Alternar ancho">&#11036;</button><button class="sh-ctrl-btn drag-handle" title="Mover">&#10303;</button></div></div><div class="section-body"><div id="chartFlow"></div></div></div>
    <div class="section full-width" data-panel="heatmap" draggable="true"><div class="section-header"><div class="sh-left"><h2>Mapa de calor por hora del d&iacute;a</h2><p>Promedio de cada m&eacute;trica por hora (Bolivia) usando todos los snapshots disponibles. Valores normalizados por fila.</p></div><div class="sh-controls"><button class="sh-ctrl-btn size-toggle" title="Alternar ancho">&#11036;</button><button class="sh-ctrl-btn drag-handle" title="Mover">&#10303;</button></div></div><div class="section-body"><div id="chartHeatmap"></div></div></div>
  </div><!-- /panel-grid -->
</div><!-- /content -->
<div class="footer"><strong>Binance P2P USDT/BOB</strong> &mdash; Dashboard &middot; <span id="footerText"></span></div>

<script>
const DATA = __DATA_PLACEHOLDER__;
const datasets = {all:DATA.ts, hourly:DATA.hourly, daily:DATA.daily};
const meta = DATA.meta, last = DATA.ts[DATA.ts.length-1];

// ═══ THEMES ═══
const THEMES = {
  paper:{'bg-primary':'#f7f5f0','bg-secondary':'#ffffff','bg-tertiary':'#eeece6','border-color':'#ddd9d0','text-primary':'#1a1a1a','text-secondary':'#5c5c5c','text-muted':'#9a9a9a','green':'#2d7a4f','green-muted':'rgba(45,122,79,0.10)','orange':'#b35c1e','orange-muted':'rgba(179,92,30,0.10)','blue-accent':'#3b6fb5','kpi-value-size':'28px'},
  claude:{'bg-primary':'#ece5d8','bg-secondary':'#f5f0e8','bg-tertiary':'#e2dace','border-color':'#d1c9ba','text-primary':'#2b2520','text-secondary':'#6b6056','text-muted':'#998e80','green':'#407a56','green-muted':'rgba(64,122,86,0.10)','orange':'#b8652a','orange-muted':'rgba(184,101,42,0.10)','blue-accent':'#8b6d4a','kpi-value-size':'28px'},
  slate:{'bg-primary':'#0f1115','bg-secondary':'#161a20','bg-tertiary':'#1e2228','border-color':'#2a2f38','text-primary':'#dce0e8','text-secondary':'#7c828e','text-muted':'#484e58','green':'#4faa72','green-muted':'rgba(79,170,114,0.12)','orange':'#d08050','orange-muted':'rgba(208,128,80,0.12)','blue-accent':'#5a8ac0','kpi-value-size':'28px'},
  ink:{'bg-primary':'#000000','bg-secondary':'#0a0a0c','bg-tertiary':'#141416','border-color':'#222228','text-primary':'#c8cad0','text-secondary':'#68686e','text-muted':'#3e3e44','green':'#4a9e68','green-muted':'rgba(74,158,104,0.12)','orange':'#c87848','orange-muted':'rgba(200,120,72,0.12)','blue-accent':'#5580aa','kpi-value-size':'28px'}
};
const LIGHT_THEMES = ['paper','claude'];

let currentTheme='paper', currentView='hourly', activeThemeValues={...THEMES.paper};

// ═══ UTILS ═══
function hexToRgba(h,a){h=(h||'').trim();if(h.startsWith('rgba')||h.startsWith('rgb'))return h;if(!h.startsWith('#')||h.length<7)return h;return'rgba('+parseInt(h.slice(1,3),16)+','+parseInt(h.slice(3,5),16)+','+parseInt(h.slice(5,7),16)+','+a+')'}
function hexLuminance(h){h=(h||'').trim();if(!h.startsWith('#')||h.length<7)return 0;const r=parseInt(h.slice(1,3),16),g=parseInt(h.slice(3,5),16),b=parseInt(h.slice(5,7),16);return(0.299*r+0.587*g+0.114*b)/255}
function isLightTheme(id){if(LIGHT_THEMES.includes(id))return true;if(id&&id.startsWith('custom:')){return hexLuminance(activeThemeValues['bg-primary'])>.5}return false}

// ═══ STORAGE ═══
function loadSaved(){try{return JSON.parse(localStorage.getItem('dashboard-custom-themes')||'[]')}catch(e){return[]}}
function persistSaved(a){localStorage.setItem('dashboard-custom-themes',JSON.stringify(a))}
function resolveTheme(id){if(THEMES[id])return{...THEMES[id]};if(id&&id.startsWith('custom:')){const f=loadSaved().find(t=>t.name===id.slice(7));if(f)return{...f.colors}}return{...THEMES.paper}}

// ═══ THEME ENGINE ═══
function applyTheme(id){
  currentTheme=id; activeThemeValues=resolveTheme(id);
  const root=document.documentElement;
  for(const[k,v]of Object.entries(activeThemeValues))root.style.setProperty('--'+k,v);
  localStorage.setItem('dashboard-active-theme',id);
  // Update bar buttons
  document.querySelectorAll('.theme-bar .theme-btn[data-theme]').forEach(b=>{b.classList.toggle('active',b.dataset.theme===id)});
  // Mark ink item in Otros dropdown
  const inkItem=document.querySelector('#othersDd .tb-dd-item[data-id="ink"]');
  if(inkItem)inkItem.classList.toggle('is-active',id==='ink');
  // Mark active in custom list
  renderCustomList();
  replotAllCharts();
}

function updateCpInputs(){
  [['cp-bg-primary','bg-primary'],['cp-bg-secondary','bg-secondary'],['cp-border-color','border-color'],
   ['cp-text-primary','text-primary'],['cp-text-secondary','text-secondary'],['cp-green','green'],
   ['cp-orange','orange'],['cp-blue-accent','blue-accent']].forEach(([id,k])=>{
    const el=document.getElementById(id);
    if(el&&activeThemeValues[k]&&activeThemeValues[k].startsWith('#'))el.value=activeThemeValues[k];
  });
}

// ═══ CUSTOM LIST RENDER ═══
function renderCustomList(){
  const saved=loadSaved(), container=document.getElementById('customList');
  if(!saved.length){container.innerHTML='<div class="tb-dd-empty">Sin temas custom</div>';return}
  container.innerHTML=saved.map(t=>{
    const id='custom:'+t.name, active=currentTheme===id;
    return'<div class="tb-dd-item'+(active?' is-active':'')+'" data-id="'+id+'">'+
      '<div class="dd-dot" style="background:'+t.colors['bg-primary']+'"></div>'+
      '<span>'+t.name+'</span>'+
      '<button class="dd-del" data-name="'+t.name+'" title="Eliminar">&times;</button></div>';
  }).join('');
  container.querySelectorAll('.tb-dd-item').forEach(item=>{
    item.addEventListener('click',e=>{if(e.target.classList.contains('dd-del'))return;closeAllPanels();applyTheme(item.dataset.id)});
  });
  container.querySelectorAll('.dd-del').forEach(btn=>{
    btn.addEventListener('click',e=>{
      e.stopPropagation();
      persistSaved(loadSaved().filter(t=>t.name!==btn.dataset.name));
      if(currentTheme==='custom:'+btn.dataset.name)applyTheme('paper');
      renderCustomList();
    });
  });
}

// ═══ PANEL MANAGEMENT ═══
function closeAllPanels(){document.getElementById('othersDd').classList.remove('open');document.getElementById('editDd').classList.remove('open')}

// ═══ PLOTLY ═══
function getC(){const t=activeThemeValues;return{gridcolor:t['border-color'],fontcolor:t['text-secondary'],green:t.green,greenMuted:t['green-muted'],orange:t.orange,orangeMuted:t['orange-muted'],blue:t['blue-accent'],textPrimary:t['text-primary'],textMuted:t['text-muted'],bgTertiary:t['bg-tertiary'],borderColor:t['border-color']}}
function BL(c){return{paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',dragmode:'pan',font:{family:'Outfit,sans-serif',color:c.fontcolor,size:10.5},margin:{l:48,r:16,t:8,b:32},xaxis:{gridcolor:hexToRgba(c.gridcolor,.5),tickfont:{family:'IBM Plex Mono,monospace',size:10,color:c.textMuted},zeroline:false,showgrid:false,showline:false,tickangle:-30},yaxis:{gridcolor:hexToRgba(c.gridcolor,.5),tickfont:{family:'IBM Plex Mono,monospace',size:10,color:c.textMuted},zeroline:false,showline:false,gridwidth:1},legend:{orientation:'h',y:-.22,font:{size:11,family:'Outfit',color:c.fontcolor}},hoverlabel:{font:{family:'IBM Plex Mono',size:11,color:c.textPrimary},bgcolor:c.bgTertiary,bordercolor:c.borderColor},hovermode:'x unified'}}
const PC={displayModeBar:false,responsive:true,scrollZoom:true};
function makeDates(ts){return ts.map(d=>{const dt=new Date(d.ts);return new Date(dt.getTime()-4*3600000)})}
function xaWithSlider(xa){xa.rangeslider={visible:true,thickness:0.06};return xa}
function xaxisForView(base){
  const cfg={...base};
  if(currentView==='daily'){cfg.dtick=86400000;cfg.tickformat='%d/%m'}
  else if(currentView==='hourly'){cfg.dtick=6*3600000;cfg.tickformat='%d/%m %H:00'}
  else{cfg.dtick=2*3600000;cfg.tickformat='%d/%m %H:%M'}
  return cfg;
}

function rVwap(c,ts,x){const L=BL(c);const traces=[{x:x,y:ts.map(d=>d.vb50),line:{color:'transparent',width:0},showlegend:false,hoverinfo:'skip'},{x:x,y:ts.map(d=>d.vb25),fill:'tonexty',fillcolor:c.greenMuted,line:{color:'transparent',width:0},showlegend:false,hoverinfo:'skip'},{x:x,y:ts.map(d=>d.vb5),fill:'tonexty',fillcolor:c.greenMuted,line:{color:hexToRgba(c.green,.3),width:.5,dash:'dot'},showlegend:false,hoverinfo:'skip'},{x:x,y:ts.map(d=>d.vb10),name:'Compra VWAP 10%',line:{color:c.green,width:2},mode:'lines'},{x:x,y:ts.map(d=>d.vs50),line:{color:'transparent',width:0},showlegend:false,hoverinfo:'skip'},{x:x,y:ts.map(d=>d.vs25),fill:'tonexty',fillcolor:c.orangeMuted,line:{color:'transparent',width:0},showlegend:false,hoverinfo:'skip'},{x:x,y:ts.map(d=>d.vs5),fill:'tonexty',fillcolor:c.orangeMuted,line:{color:hexToRgba(c.orange,.3),width:.5,dash:'dot'},showlegend:false,hoverinfo:'skip'},{x:x,y:ts.map(d=>d.vs10),name:'Venta VWAP 10%',line:{color:c.orange,width:2},mode:'lines'},{x:x,y:ts.map(()=>meta.bcb_rate),name:'BCB '+meta.bcb_rate,line:{color:c.textMuted,width:1,dash:'dash'},visible:'legendonly'}];if(meta.bcb_ref_history&&meta.bcb_ref_history.length){const hist=meta.bcb_ref_history;if(hist.length===1){const e=hist[0];traces.push({x:x,y:ts.map(()=>e.compra),name:'BCB Ref Compra '+e.compra,line:{color:c.blue,width:1,dash:'dot'}});traces.push({x:x,y:ts.map(()=>e.venta),name:'BCB Ref Venta '+e.venta,line:{color:c.blue,width:1.5,dash:'dot'}})}else{const hx=hist.map(e=>new Date(e.fecha+'T00:00:00'));traces.push({x:hx,y:hist.map(e=>e.compra),name:'BCB Ref Compra',line:{color:c.blue,width:1,dash:'dot'},mode:'lines+markers',marker:{size:4,color:c.blue},connectgaps:true});traces.push({x:hx,y:hist.map(e=>e.venta),name:'BCB Ref Venta',line:{color:c.blue,width:1.5,dash:'dot'},mode:'lines+markers',marker:{size:4,color:c.blue},connectgaps:true})}}Plotly.react('chartVwap',traces,{...L,xaxis:xaWithSlider(xaxisForView(L.xaxis)),yaxis:{...L.yaxis,tickformat:'.2f'},margin:{l:48,r:16,t:36,b:80},legend:{orientation:'h',y:1.08,yanchor:'bottom',x:0,xanchor:'left',font:{size:11,family:'Outfit',color:c.fontcolor}},height:chartHeight('chartVwap')+40},PC)}
function rSpread(c,ts,x){const L=BL(c);Plotly.react('chartSpread',[{x:x,y:ts.map(d=>d.sp5),name:'5%',line:{color:hexToRgba(c.blue,.3),width:1,dash:'dot'}},{x:x,y:ts.map(d=>d.sp10),name:'10%',line:{color:c.blue,width:2},mode:'lines'},{x:x,y:ts.map(d=>d.sp25),name:'25%',line:{color:hexToRgba(c.blue,.5),width:1.2}},{x:x,y:ts.map(d=>d.sp50),name:'50%',line:{color:hexToRgba(c.blue,.25),width:1}}],{...L,xaxis:xaWithSlider(xaxisForView(L.xaxis)),yaxis:{...L.yaxis,title:{text:'BOB',font:{size:10,color:c.textMuted}},tickformat:'.3f'},height:chartHeight('chartSpread')},PC)}
function rDepth(c,ts,x){const L=BL(c);Plotly.react('chartDepth',[{x:x,y:ts.map(d=>d.buy_depth),name:'Compra',fill:'tozeroy',fillcolor:c.greenMuted,line:{color:c.green,width:1.5}},{x:x,y:ts.map(d=>d.sell_depth),name:'Venta',fill:'tozeroy',fillcolor:c.orangeMuted,line:{color:c.orange,width:1.5}}],{...L,xaxis:xaWithSlider(xaxisForView(L.xaxis)),yaxis:{...L.yaxis,tickformat:',.0f'},height:chartHeight('chartDepth')},PC)}
function rRatio(c,ts,x){const L=BL(c);Plotly.react('chartRatio',[{x:x,y:ts.map(d=>d.depth_ratio),name:'SELL/BUY',fill:'tozeroy',fillcolor:hexToRgba(c.blue,.08),line:{color:c.blue,width:1.5},mode:'lines'},{x:x,y:ts.map(()=>1),name:'Equilibrio',line:{color:c.textMuted,width:.8,dash:'dash'}}],{...L,xaxis:xaWithSlider(xaxisForView(L.xaxis)),yaxis:{...L.yaxis,tickformat:'.1f'},height:chartHeight('chartRatio')},PC)}
function rConc(c,ts,x){const L=BL(c);Plotly.react('chartConc',[{x:x,y:ts.map(d=>d.t5buy),name:'Top 5 compra',line:{color:c.green,width:1.5},mode:'lines'},{x:x,y:ts.map(d=>d.t5sell),name:'Top 5 venta',line:{color:c.orange,width:1.5},mode:'lines'}],{...L,xaxis:xaWithSlider(xaxisForView(L.xaxis)),yaxis:{...L.yaxis,ticksuffix:'%',tickformat:'.0f',rangemode:'tozero'},height:chartHeight('chartConc')},PC)}
function rDecile(c){const L=BL(c),dB=DATA.deciles[meta.last_ts].BUY,dS=DATA.deciles[meta.last_ts].SELL,dl=['10%','20%','30%','40%','50%','60%','70%','80%','90%','100%'];Plotly.react('chartDecile',[{x:dl,y:dB,name:'Compra',type:'bar',marker:{color:hexToRgba(c.green,.55),line:{color:c.green,width:.5}}},{x:dl,y:dS,name:'Venta',type:'bar',marker:{color:hexToRgba(c.orange,.55),line:{color:c.orange,width:.5}}}],{...L,barmode:'group',bargap:.3,bargroupgap:.06,showlegend:true,xaxis:{...L.xaxis,title:{text:'Profundidad acumulada',font:{size:10,color:c.textMuted}},tickangle:0},yaxis:{...L.yaxis,tickformat:'.2f',range:[Math.min(...dS)*.998,Math.max(...dB)*1.002]},height:chartHeight('chartDecile')},PC)}
function rBank(c){const bk=DATA.banks;if(!bk.length)return;const mx=Math.max(...bk.map(b=>b.depth)),bc=hexToRgba(c.blue,.2);document.getElementById('bankTable').innerHTML='<table class="bank-table"><thead><tr><th>Banco</th><th>Anuncios</th><th>Profundidad (USDT)</th><th>Cobertura</th></tr></thead><tbody>'+bk.map(b=>'<tr><td>'+b.name+'</td><td>'+b.count+'</td><td class="bar-cell"><div class="bar-fill" style="width:'+(b.depth/mx*100)+'%;background:'+bc+'"></div>'+b.depth.toLocaleString()+'</td><td>'+b.depth_pct+'%</td></tr>').join('')+'</tbody></table>'}

// ── New panel renderers ──
function currentViewLastTs(){const ts=datasets[currentView];return(ts&&ts.length)?ts[ts.length-1].ts:meta.last_ts}

function rMerchants(){
  const key=currentViewLastTs();
  const data=(DATA.top_merchants||{})[key]||(DATA.top_merchants||{})[meta.last_ts];
  if(!data){document.getElementById('topMerchants').innerHTML='<div class="view-hint">Sin datos de merchants</div>';return}
  const renderSide=(label,arr)=>{
    if(!arr||!arr.length)return '<div class="merchants-side"><h3>'+label+'</h3><div class="view-hint">Sin datos</div></div>';
    const rows=arr.map((m,i)=>'<tr>'+
      '<td>'+(i+1)+'</td>'+
      '<td class="nick" title="'+(m.nick||'').replace(/"/g,'&quot;')+'">'+(m.nick||'')+'</td>'+
      '<td class="num">'+(m.depth!=null?m.depth.toLocaleString():'-')+'</td>'+
      '<td class="num">'+(m.pct!=null?m.pct+'%':'-')+'</td>'+
      '<td class="num">'+(m.vwap!=null?m.vwap.toFixed(4):'-')+'</td>'+
      '<td class="num">'+(m.n_banks!=null?m.n_banks:'-')+'</td>'+
      '<td class="num">'+(m.month_order_count!=null?m.month_order_count.toLocaleString():'-')+'</td>'+
    '</tr>').join('');
    return '<div class="merchants-side"><h3>'+label+'</h3><table class="merchants-table">'+
      '<thead><tr><th>#</th><th>Nick</th><th>USDT</th><th>%</th><th>VWAP</th><th>Bancos</th><th>Trades/mes</th></tr></thead>'+
      '<tbody>'+rows+'</tbody></table></div>';
  };
  document.getElementById('topMerchants').innerHTML='<div class="merchants-grid">'+renderSide('BUY',data.BUY)+renderSide('SELL',data.SELL)+'</div>';
}

function rVolatility(c){
  const el=document.getElementById('chartVolatility');
  if(currentView!=='daily'){
    el.innerHTML='<div class="view-hint">Cambi&aacute; a vista &quot;Por d&iacute;a&quot; para ver este gr&aacute;fico.</div>';
    return;
  }
  el.innerHTML='';
  const v=DATA.volatility_daily||[];
  if(!v.length){el.innerHTML='<div class="view-hint">Sin datos de volatilidad</div>';return}
  const L=BL(c), xa=xaxisForView(L.xaxis);
  Plotly.react('chartVolatility',[
    {x:v.map(d=>d.date),y:v.map(d=>d.buy_range),name:'BUY (rango)',type:'bar',marker:{color:c.green}},
    {x:v.map(d=>d.date),y:v.map(d=>d.sell_range),name:'SELL (rango)',type:'bar',marker:{color:c.orange}},
  ],{...L,barmode:'group',xaxis:{...L.xaxis,type:'category'},yaxis:{...L.yaxis,title:{text:'BOB',font:{size:10,color:c.textMuted}},tickformat:'.4f',rangemode:'tozero'},showlegend:true,height:chartHeight('chartVolatility')},PC);
}

function rFlow(c){
  const L=BL(c);
  const flow=(DATA.merchant_flow||{})[currentView]||[];
  if(!flow.length){document.getElementById('chartFlow').innerHTML='<div class="view-hint">Sin datos</div>';return}
  const x=flow.map(f=>{const dt=new Date(f.ts);return new Date(dt.getTime()-4*3600000)});
  Plotly.react('chartFlow',[
    {x:x,y:flow.map(f=>f.new_buy),name:'Nuevos BUY',type:'bar',marker:{color:hexToRgba(c.green,.5)}},
    {x:x,y:flow.map(f=>-f.gone_buy),name:'Desap. BUY',type:'bar',marker:{color:hexToRgba(c.green,.2)}},
    {x:x,y:flow.map(f=>f.new_sell),name:'Nuevos SELL',type:'bar',marker:{color:hexToRgba(c.orange,.5)}},
    {x:x,y:flow.map(f=>-f.gone_sell),name:'Desap. SELL',type:'bar',marker:{color:hexToRgba(c.orange,.2)}},
    {x:x,y:flow.map(f=>f.n_buy),name:'Total BUY',yaxis:'y2',line:{color:c.green,width:2},mode:'lines'},
    {x:x,y:flow.map(f=>f.n_sell),name:'Total SELL',yaxis:'y2',line:{color:c.orange,width:2},mode:'lines'},
  ],{...L,barmode:'relative',xaxis:xaWithSlider(xaxisForView(L.xaxis)),yaxis:{...L.yaxis,title:{text:'Flujo',font:{size:10,color:c.textMuted}},tickformat:'.0f'},yaxis2:{overlaying:'y',side:'right',showgrid:false,tickfont:{family:'IBM Plex Mono,monospace',size:10,color:c.textMuted},title:{text:'Total',font:{size:10,color:c.textMuted}}},showlegend:true,height:chartHeight('chartFlow')},PC);
}

function rHeatmap(c){
  const hm=DATA.heatmap;
  if(!hm||!hm.metrics||!hm.metrics.length){document.getElementById('chartHeatmap').innerHTML='<div class="view-hint">Sin datos</div>';return}
  // Normalize each row 0..1 for color; keep real values in customdata for hover
  const z=[], text=[], labels=[];
  for(const m of hm.metrics){
    labels.push(m.label);
    const vals=m.values;
    const nums=vals.filter(v=>v!=null);
    const mn=Math.min(...nums), mx=Math.max(...nums), rng=(mx-mn)||1;
    z.push(vals.map(v=>v==null?null:(v-mn)/rng));
    text.push(vals.map(v=>v==null?'—':v.toLocaleString(undefined,{maximumFractionDigits:4})));
  }
  const L=BL(c);
  const cs=[[0,hexToRgba(c.blue,.05)],[0.5,hexToRgba(c.blue,.35)],[1,c.blue]];
  Plotly.react('chartHeatmap',[{
    z:z,x:hm.hours.map(h=>String(h).padStart(2,'0')+'h'),y:labels,
    type:'heatmap',colorscale:cs,showscale:false,
    text:text,texttemplate:'%{text}',hovertemplate:'%{y}<br>%{x}: %{text}<extra></extra>',
    xgap:1,ygap:1,
  }],{...L,margin:{l:130,r:16,t:8,b:40},xaxis:{...L.xaxis,tickangle:0,side:'bottom',type:'category',showgrid:false},yaxis:{...L.yaxis,automargin:true,showgrid:false},height:chartHeight('chartHeatmap')},PC);
}

function renderTimeSeries(v){currentView=v;const c=getC(),ts=datasets[v],x=makeDates(ts);rVwap(c,ts,x);rSpread(c,ts,x);rDepth(c,ts,x);rRatio(c,ts,x);rConc(c,ts,x);rMerchants();rVolatility(c);rFlow(c)}
function replotAllCharts(){const c=getC(),ts=datasets[currentView],x=makeDates(ts);rVwap(c,ts,x);rSpread(c,ts,x);rDepth(c,ts,x);rRatio(c,ts,x);rConc(c,ts,x);rDecile(c);rBank(c);rMerchants();rVolatility(c);rFlow(c);rHeatmap(c)}

// ═══ STATIC CONTENT ═══
document.getElementById('headerMeta').innerHTML='<strong>'+meta.total_snapshots+'</strong> snapshots &middot; <strong>'+meta.total_ads.toLocaleString()+'</strong> registros<br>'+new Date(meta.first_ts).toLocaleDateString('es-BO',{day:'numeric',month:'long',year:'numeric'})+' &mdash; '+new Date(meta.last_ts).toLocaleDateString('es-BO',{day:'numeric',month:'long',year:'numeric'});
const premium=((last.vb10/meta.bcb_rate-1)*100).toFixed(1);
document.getElementById('kpis').innerHTML='<div class="kpi"><div class="label">VWAP 10% Compra</div><div class="value buy">'+last.vb10.toFixed(4)+'</div><div class="sub">BOB por USDT</div></div><div class="kpi"><div class="label">VWAP 10% Venta</div><div class="value sell">'+last.vs10.toFixed(4)+'</div><div class="sub">BOB por USDT</div></div><div class="kpi"><div class="label">Spread efectivo</div><div class="value spread">'+last.sp10.toFixed(4)+'</div><div class="sub">'+(last.sp10/last.vb10*100).toFixed(2)+'% del precio</div></div><div class="kpi"><div class="label">Profundidad compra</div><div class="value">'+(last.buy_depth/1e6).toFixed(2)+'M</div><div class="sub">'+last.buy_count+' anuncios</div></div><div class="kpi"><div class="label">Profundidad venta</div><div class="value">'+(last.sell_depth/1e6).toFixed(2)+'M</div><div class="sub">'+last.sell_count+' anuncios</div></div><div class="kpi"><div class="label">Asimetr\u00eda</div><div class="value">'+last.depth_ratio.toFixed(1)+'\u00d7</div><div class="sub">m\u00e1s oferta que demanda</div></div><div class="kpi"><div class="label">Tipo oficial BCB</div><div class="value">'+meta.bcb_rate+'</div><div class="sub">prima paralela: +'+premium+'%</div></div>'+(meta.bcb_ref_venta!=null?'<div class="kpi"><div class="label">TC Referencial BCB</div><div class="value spread">'+meta.bcb_ref_venta.toFixed(2)+'</div><div class="sub">Compra: '+meta.bcb_ref_compra.toFixed(2)+' &middot; Fuente: BCB</div></div>':'');
document.getElementById('footerText').textContent='Dashboard generado: '+new Date().toLocaleString('es-BO')+' \u00b7 '+meta.total_snapshots+' snapshots procesados';

// ═══ EVENTS ═══
// View toggle
document.querySelectorAll('.toggle-btn').forEach(b=>{b.addEventListener('click',()=>{document.querySelectorAll('.toggle-btn').forEach(x=>x.classList.remove('active'));b.classList.add('active');renderTimeSeries(b.dataset.view)})});

// Preset theme buttons
document.querySelectorAll('.theme-bar > .theme-btn[data-theme]').forEach(b=>{
  b.addEventListener('click',()=>{closeAllPanels();applyTheme(b.dataset.theme)});
});

// Others dropdown
document.getElementById('othersBtn').addEventListener('click',e=>{
  e.stopPropagation();
  const dd=document.getElementById('othersDd'), ed=document.getElementById('editDd');
  ed.classList.remove('open');
  dd.classList.toggle('open');
});
// "Negro" preset item in Otros
document.querySelector('#othersDd .tb-dd-item[data-id="ink"]').addEventListener('click',()=>{closeAllPanels();applyTheme('ink')});

// Edit dropdown
document.getElementById('editBtn').addEventListener('click',e=>{
  e.stopPropagation();
  const dd=document.getElementById('editDd'), od=document.getElementById('othersDd');
  od.classList.remove('open');
  dd.classList.toggle('open');
  if(dd.classList.contains('open'))updateCpInputs();
});

// Click outside closes panels
document.addEventListener('click',e=>{
  if(!document.getElementById('othersWrap').contains(e.target))document.getElementById('othersDd').classList.remove('open');
  if(!document.getElementById('editWrap').contains(e.target))document.getElementById('editDd').classList.remove('open');
});
// Escape closes panels
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeAllPanels()});

// Color pickers with debounce
const cpMap=[['cp-bg-primary','bg-primary'],['cp-bg-secondary','bg-secondary'],['cp-border-color','border-color'],['cp-text-primary','text-primary'],['cp-text-secondary','text-secondary'],['cp-green','green'],['cp-orange','orange'],['cp-blue-accent','blue-accent']];
let rpT=null;
function applyCssVar(vn,val){
  activeThemeValues[vn]=val;document.documentElement.style.setProperty('--'+vn,val);
  if(vn==='green'){const m=hexToRgba(val,.12);activeThemeValues['green-muted']=m;document.documentElement.style.setProperty('--green-muted',m)}
  else if(vn==='orange'){const m=hexToRgba(val,.12);activeThemeValues['orange-muted']=m;document.documentElement.style.setProperty('--orange-muted',m)}
  else if(vn==='bg-secondary'){activeThemeValues['bg-tertiary']=val;document.documentElement.style.setProperty('--bg-tertiary',val)}
  else if(vn==='text-secondary'){activeThemeValues['text-muted']=val;document.documentElement.style.setProperty('--text-muted',val)}
}
cpMap.forEach(([id,vn])=>{
  const el=document.getElementById(id);
  el.addEventListener('input',function(){applyCssVar(vn,this.value);clearTimeout(rpT);rpT=setTimeout(()=>replotAllCharts(),300)});
  el.addEventListener('change',function(){applyCssVar(vn,this.value);clearTimeout(rpT);replotAllCharts()});
});

// Save as
document.getElementById('cpSaveAs').addEventListener('click',()=>{
  const name=prompt('Nombre del tema (max 20 chars):');
  if(!name||!name.trim())return;
  const n=name.trim().slice(0,20), saved=loadSaved().filter(t=>t.name!==n);
  if(saved.length>=5){alert('M\u00e1ximo 5 temas. Elimin\u00e1 uno primero.');return}
  const colors={};for(const k of Object.keys(THEMES.paper))colors[k]=activeThemeValues[k];
  saved.push({name:n,colors});persistSaved(saved);
  applyTheme('custom:'+n);closeAllPanels();
});

// Export JSON
document.getElementById('cpExport').addEventListener('click',()=>{
  const exp={};cpMap.forEach(([_,k])=>exp[k]=activeThemeValues[k]);
  const obj={name:currentTheme.startsWith('custom:')?currentTheme.slice(7):'Mi tema',colors:exp};
  navigator.clipboard.writeText(JSON.stringify(obj,null,2)).then(()=>{
    const b=document.getElementById('cpExport');b.textContent='Copiado!';setTimeout(()=>b.textContent='Export JSON',1500);
  });
});

// Reset
document.getElementById('cpReset').addEventListener('click',()=>{closeAllPanels();applyTheme('paper')});

// Import
document.getElementById('importBtn').addEventListener('click',()=>{
  const text=prompt('Peg\u00e1 el JSON del tema:');
  if(!text)return;
  try{
    const obj=JSON.parse(text);
    if(!obj.name||!obj.colors||!obj.colors['bg-primary']||!obj.colors.green){alert('JSON inv\u00e1lido. Debe tener name y colors con todas las variables.');return}
    const saved=loadSaved().filter(t=>t.name!==obj.name);
    if(saved.length>=5){alert('M\u00e1ximo 5 temas. Elimin\u00e1 uno primero.');return}
    const c=obj.colors;
    if(!c['green-muted'])c['green-muted']=hexToRgba(c.green,.12);
    if(!c['orange-muted'])c['orange-muted']=hexToRgba(c.orange,.12);
    if(!c['bg-tertiary'])c['bg-tertiary']=c['bg-secondary']||c['bg-primary'];
    if(!c['text-muted'])c['text-muted']=c['text-secondary']||'#999';
    if(!c['kpi-value-size'])c['kpi-value-size']='28px';
    saved.push({name:obj.name,colors:c});persistSaved(saved);
    closeAllPanels();applyTheme('custom:'+obj.name);
  }catch(e){alert('Error al parsear JSON: '+e.message)}
});

// ═══ PANEL LAYOUT (drag + resize + persist) ═══
const DEFAULT_LAYOUT = [
  {id:'vwap',full:true},{id:'spread',full:false},{id:'depth',full:false},
  {id:'decile',full:false},{id:'ratio',full:false},{id:'conc',full:false},{id:'bank',full:false},
  {id:'merchants',full:true},{id:'volatility',full:false},{id:'flow',full:false},{id:'heatmap',full:true}
];

function loadLayout(){
  try{const s=localStorage.getItem('dashboard-layout');if(s)return JSON.parse(s)}catch(e){}
  return null;
}
function saveLayout(){
  const grid=document.getElementById('panelGrid');
  const layout=[...grid.children].map(el=>({id:el.dataset.panel,full:el.classList.contains('full-width')}));
  localStorage.setItem('dashboard-layout',JSON.stringify(layout));
}
function applyLayout(layout){
  const grid=document.getElementById('panelGrid');
  const panels={};
  [...grid.children].forEach(el=>{panels[el.dataset.panel]=el});
  layout.forEach(item=>{
    const el=panels[item.id];
    if(!el)return;
    el.classList.toggle('full-width',!!item.full);
    grid.appendChild(el);
  });
}
function chartHeight(divId){const el=document.getElementById(divId);if(!el)return 300;const panel=el.closest('.section');return(panel&&panel.classList.contains('full-width'))?400:300}
function resizePanelCharts(panel){
  const isFull=panel.classList.contains('full-width');
  const h=isFull?400:300;
  requestAnimationFrame(()=>{setTimeout(()=>{
    const plots=panel.querySelectorAll('.js-plotly-plot');
    plots.forEach(p=>{Plotly.relayout(p,{height:h,autosize:true}).then(()=>Plotly.Plots.resize(p))});
  },50)});
}
function updateToggleIcon(btn,isFull){btn.innerHTML=isFull?'\u2921':'\u2922'}

// Size toggle buttons
document.querySelectorAll('.size-toggle').forEach(btn=>{
  btn.addEventListener('click',()=>{
    const panel=btn.closest('.section');
    panel.classList.toggle('full-width');
    const isFull=panel.classList.contains('full-width');
    updateToggleIcon(btn,isFull);
    saveLayout();
    resizePanelCharts(panel);
  });
});

// Drag and drop
let draggedPanel=null;
document.querySelectorAll('.panel-grid .section').forEach(panel=>{
  // Only start drag from handle
  panel.addEventListener('dragstart',e=>{
    if(!e.target.closest('.drag-handle')&&e.target!==panel){e.preventDefault();return}
    draggedPanel=panel;
    panel.classList.add('dragging');
    e.dataTransfer.effectAllowed='move';
    e.dataTransfer.setData('text/plain','');
  });
  panel.addEventListener('dragend',()=>{
    if(draggedPanel)draggedPanel.classList.remove('dragging');
    document.querySelectorAll('.section.drag-over').forEach(el=>el.classList.remove('drag-over'));
    draggedPanel=null;
    saveLayout();
    // Resize all plotly charts after reorder
    document.querySelectorAll('.panel-grid .js-plotly-plot').forEach(p=>Plotly.Plots.resize(p));
  });
  panel.addEventListener('dragover',e=>{
    e.preventDefault();
    e.dataTransfer.dropEffect='move';
    if(panel!==draggedPanel)panel.classList.add('drag-over');
  });
  panel.addEventListener('dragleave',()=>panel.classList.remove('drag-over'));
  panel.addEventListener('drop',e=>{
    e.preventDefault();
    panel.classList.remove('drag-over');
    if(!draggedPanel||panel===draggedPanel)return;
    const grid=document.getElementById('panelGrid');
    const all=[...grid.children];
    const fromIdx=all.indexOf(draggedPanel), toIdx=all.indexOf(panel);
    if(fromIdx<toIdx)panel.after(draggedPanel);
    else panel.before(draggedPanel);
  });
  // Make drag only work from handle
  panel.addEventListener('mousedown',e=>{
    panel.draggable=!!e.target.closest('.drag-handle');
  });
});

// ═══ INIT ═══
(function(){
  // Restore layout
  const layout=loadLayout();
  if(layout)applyLayout(layout);
  // Set initial toggle icons
  document.querySelectorAll('.panel-grid .section').forEach(p=>{
    const btn=p.querySelector('.size-toggle');
    if(btn)updateToggleIcon(btn,p.classList.contains('full-width'));
  });
  renderCustomList();
  const saved=localStorage.getItem('dashboard-active-theme');
  const customIds=loadSaved().map(t=>'custom:'+t.name);
  if(saved&&(THEMES[saved]||customIds.includes(saved)))applyTheme(saved);
  else applyTheme('paper');
  renderTimeSeries('hourly');
})();
</script>
</body></html>
"""


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Genera dashboard HTML desde SQLite")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help=f"Base SQLite (default: {DEFAULT_DB})")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"HTML de salida (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--csv", action="store_true",
                        help="También exportar CSV con métricas por snapshot")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"No se encontró {args.db}. Corré normalize.py primero.", file=sys.stderr)
        sys.exit(1)

    print(f"Leyendo {args.db} ...")
    data = process_data(args.db)

    print(f"  {data['meta']['total_snapshots']} snapshots, "
          f"{data['meta']['total_ads']:,} anuncios")

    html = HTML_TEMPLATE.replace('__DATA_PLACEHOLDER__', json.dumps(data))

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Dashboard: {args.output} ({args.output.stat().st_size / 1024:.1f} KB)")
    # Alias por compatibilidad (si el output default es index.html, también escribir p2p_dashboard.html)
    if args.output.name == 'index.html':
        alias = args.output.with_name('p2p_dashboard.html')
        with open(alias, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"Alias:     {alias}")

    if args.csv:
        csv_path = args.output.with_name('p2p_metrics.csv')
        export_hourly_csv(data, csv_path)

    print("Abrí el .html en cualquier navegador para ver el dashboard.")


if __name__ == "__main__":
    main()
