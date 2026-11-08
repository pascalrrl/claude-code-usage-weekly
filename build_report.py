#!/usr/bin/env python3
"""Merge all week files data/<computer>/<week>.json and write report.html.

    python3 build_report.py

The quota of a week is the API-price equivalent of all computers from the start of the week up to
the first weekly-limit message: after it no request gets through. A full week without that message
gives only a lower bound.

Costs are computed here, from the token counts of the week files and the prices in prices.json
that were valid in each hour, so a corrected or added price applies to every week on the next run.

A week is full when every computer counted it from its start to its end. A new computer (see
new_pc) counts as full with $0 before its first transcript. Only full weeks go into mean, band and
trend; partly counted weeks are drawn faded. Display names of the computers can be set in
settings.json ("computers"); several folders with the same name are added up.
"""
import collections, datetime as dt, glob, json, os, re, sys

import scan_usage as su  # limit weeks, settings.json and the week files
from scan_usage import HERE, TOKEN_FIELDS, UTC, SettingsError, parse_ts as ts

FIELDS = ('requests', 'input', 'output', 'cache_write', 'cache_read', 'cost_usd')
KEEP_DAYS = 30  # shortest retention of transcripts (Claude Code's default cleanupPeriodDays)
NEW_MARGIN_DAYS = 7  # this far inside the retention the oldest entry must lie: a new computer
OTHERS = '_other'


def _day(v, where):
    if v is None:
        return None
    try:
        return dt.datetime.combine(su.parse_date(v), dt.time(0), UTC)
    except (TypeError, ValueError):
        raise SettingsError(f'{where}: {v!r} is not a date like 2026-10-31')


def load_prices(path=None):
    """Read and check prices.json: {model: [(from, until, rates), ...]} sorted by 'from'."""
    prices = {}
    for model, periods in su.read_json(path or os.path.join(HERE, 'prices.json')).items():
        rows = []
        for i, p in enumerate(periods):
            where = f'prices.json: {model}[{i}]'
            missing = [f for f in TOKEN_FIELDS if not isinstance(p.get(f), (int, float)) or p[f] < 0]
            if missing:
                raise SettingsError(f'{where}: {", ".join(missing)} must be a number >= 0')
            lo, hi = _day(p.get('from'), where + '.from'), _day(p.get('until'), where + '.until')
            if lo and hi and hi <= lo:
                raise SettingsError(f'{where}: "until" must be after "from"')
            rows.append((lo, hi, {f: p[f] for f in TOKEN_FIELDS}))
        rows.sort(key=lambda x: x[0] or dt.datetime.min.replace(tzinfo=UTC))
        for (lo1, hi1, _), (lo2, _, _) in zip(rows, rows[1:]):
            if hi1 is None or lo2 is None or lo2 < hi1:
                raise SettingsError(f'prices.json: {model}: periods overlap; end the older one with "until"')
        prices[model] = rows
    return prices


def model_key(model, prices):
    """Price entry for a model name (longest matching prefix), None if there is none."""
    for k in sorted(prices, key=len, reverse=True):
        if model.startswith(k):
            return k
    return None


def price_at(key, t, prices):
    """Rates in $ per million tokens of a price entry at moment t, None outside every period."""
    for lo, hi, rates in prices.get(key, ()):
        if (lo is None or lo <= t) and (hi is None or t < hi):
            return rates
    return None


def cost(tokens, rates):
    """$ for a list of token counts in TOKEN_FIELDS order."""
    return sum(n * rates[f] for n, f in zip(tokens, TOKEN_FIELDS)) / 1e6


def model_name(k):
    if k == OTHERS:
        return 'Other models'
    m = re.fullmatch(r'claude-([a-z]+)-(\d+)(?:-(\d+))?', k)
    return f'{m[1].capitalize()} {m[2]}' + (f'.{m[3]}' if m[3] else '') if m else k


def new_pc(r):
    """A new computer, not a deleted history: Claude Code deletes transcripts after KEEP_DAYS days
    at the earliest. If the oldest entry lies more than NEW_MARGIN_DAYS inside that period before
    the scan, the computer used nothing before it."""
    if not r['data_from']:
        return False
    return ts(r['data_from']) > ts(r['scanned_at']) - dt.timedelta(days=KEEP_DAYS - NEW_MARGIN_DAYS)


def load(settings, prices):
    labels = settings['computers']
    now = dt.datetime.now(UTC)
    weeks, pcs, first, skipped = {}, [], {}, []
    for path in sorted(glob.glob(os.path.join(HERE, 'data', '*', '*.json'))):
        with open(path, encoding='utf-8') as fh:
            r = json.load(fh)
        rel = os.path.relpath(path, HERE)
        if r.get('format') != su.FORMAT:
            skipped.append(f'{rel} has an older format and is skipped; count that week again with scan_usage.py')
            continue
        start, end = ts(r['week_start']), ts(r['week_end'])
        # A file counted with another weekly reset (e.g. --reset on another computer) cuts the weeks
        # differently: added up with the others it would give shifted or doubled weeks
        if su.week_start(start, settings) != start or su.week_end(start, settings) != end:
            skipped.append(f'{rel} was counted with another weekly reset (week from {r["week_start"]}) and is '
                           f'skipped; count it again with the reset {settings["reset_text"]}')
            continue
        pc = labels.get(r['pc'], r['pc'])
        if pc not in pcs:
            pcs.append(pc)
        k = su.week_key(start, settings)
        first[pc] = min(first.get(pc, k), k)
        w = weeks.setdefault(k, {'start': start, 'end': end, 'pcs': {}, 'hits': [], 'models': {}, 'unknown': set()})
        p = w['pcs'].setdefault(pc, {**dict.fromkeys(FIELDS, 0), 'hourly': collections.defaultdict(float),
                                     'until': end, 'data_ok': True, 'data_from': None})
        for name, v in r['models'].items():
            key = model_key(name, prices)
            p['requests'] += v['requests']
            p['input'] += v['input']
            p['output'] += v['output']
            p['cache_write'] += v['cache_write_5m'] + v['cache_write_1h']
            p['cache_read'] += v['cache_read']
            for h, tokens in v['hourly'].items():
                rates = price_at(key, start + dt.timedelta(hours=int(h)), prices) if key else None
                if rates is None:
                    w['unknown'].add(name)
                    continue
                c = cost(tokens, rates)
                p['hourly'][int(h)] += c
                p['cost_usd'] += c
                w['models'][key] = w['models'].get(key, 0) + c
        p['until'] = min(p['until'], ts(r['counted_until']))
        # Before its first transcript a new computer did not run: those weeks are full, with $0
        if not new_pc(r) and not (r['data_from'] and ts(r['data_from']) <= start):
            p['data_ok'] = False
            p['data_from'] = r['data_from']
        for h in r['limit_hits']:
            w['hits'].append({**h, 'pc': pc, 'time': ts(h['t'])})
    for k, w in weeks.items():
        w['missing'] = [pc for pc in pcs if first[pc] <= k and pc not in w['pcs']]
        notes = [f'{pc}: not counted' for pc in w['missing']]
        for pc, p in w['pcs'].items():
            if p['until'] < w['end']:
                notes.append(f"{pc}: counted until {p['until']:%Y-%m-%d %H:%M} UTC"
                             + (' (current week)' if w['end'] > now else ''))
            if not p['data_ok']:
                notes.append(f"{pc}: transcripts only from {ts(p['data_from']):%Y-%m-%d}" if p['data_from']
                             else f'{pc}: no transcripts')
        w['notes'] = sorted(notes)
    return pcs, weeks, skipped


def merge_hits(hits):
    """The same limit message on several computers counts once."""
    out = []
    for h in sorted(hits, key=lambda h: h['time']):
        same = next((o for o in out if o['kind'] == h['kind'] and o['text'] == h['text']
                     and h['time'] - o['time'] < su.HIT_WINDOW), None)
        if same:
            same['pcs'] += [h['pc']] if h['pc'] not in same['pcs'] else []
        else:
            out.append({**h, 'pcs': [h['pc']]})
    return out


def label(w, settings):
    s, e = (x.astimezone(settings['tz']) for x in (w['start'], w['end']))
    return f'{su.MONTHS[s.month - 1]} {s.day} – {su.MONTHS[e.month - 1]} {e.day}'


def trend(ys):
    n = len(ys)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0
    mx = (n - 1) / 2
    my = sum(ys) / n
    slope = sum((i - mx) * (y - my) for i, y in enumerate(ys)) / sum((i - mx) ** 2 for i in range(n))
    return slope, my - slope * mx


def quota(w, total):
    """Quota of the week: from the first weekly-limit message; for a full week without one, its
    usage as a lower bound."""
    def counted(t):  # every computer counted the week from its start up to t
        return not w['missing'] and all(p['data_ok'] and p['until'] >= t for p in w['pcs'].values())

    hit = next((h for h in w['hits'] if h['kind'] == 'weekly'), None)
    if hit and counted(hit['time']):
        # After the limit message no request gets through: the hour of the message counts in full
        i = int((hit['time'] - w['start']).total_seconds() // 3600)
        v = sum(c for p in w['pcs'].values() for h, c in p['hourly'].items() if h <= i)
        return {'kind': 'hit', 'value': round(v, 2), 't': hit['time'].isoformat(), 'after': max(0, round(total - v, 2))}
    if hit is None and not w['notes']:
        return {'kind': 'min', 'value': round(total, 2)}
    return None


def main():
    try:
        settings, prices = su.load_settings(), load_prices()
    except SettingsError as e:
        sys.exit(f'Error: {e}')
    pcs, weeks, skipped = load(settings, prices)
    for message in skipped:
        print(f'Warning: {message}')
    if not weeks:
        sys.exit('No week files in data/. Run scan_usage.py first.')
    keys = sorted(weeks)
    now = dt.datetime.now(UTC)
    rows = []
    for k in keys:
        w = weeks[k]
        w['hits'] = merge_hits(w['hits'])
        tot = {f: sum(p[f] for p in w['pcs'].values()) for f in FIELDS}
        tot['tokens'] = tot['input'] + tot['output'] + tot['cache_write'] + tot['cache_read']
        checks = []
        for h in w['hits']:
            r = su.reset_from_text(h['text'], h['time']) if h['kind'] == 'weekly' else None
            if r and abs(r - w['end']) > dt.timedelta(minutes=30):
                checks.append(f"Reset per limit message {r:%Y-%m-%d %H:%M} {r.tzinfo} instead of "
                              f"{w['end'].astimezone(r.tzinfo):%Y-%m-%d %H:%M}: check week_reset in settings.json")
        if w['unknown']:
            checks.append('No price in prices.json (counted as $0): ' + ', '.join(sorted(w['unknown'])))
        cost_models = sum(w['models'].values())
        rows.append({
            'week': k, 'label': label(w, settings), 'full': not w['notes'], 'running': w['end'] > now,
            'notes': w['notes'], 'checks': sorted(set(checks)),
            'limit': [h['time'].isoformat() for h in w['hits'] if h['kind'] == 'weekly'], 'total': tot,
            'hits': [{'t': h['time'].isoformat(), 'kind': h['kind'], 'text': h['text'], 'pcs': h['pcs']} for h in w['hits']],
            'session_hits': sum(h['kind'] == 'session' for h in w['hits']),
            'quota': quota(w, tot['cost_usd']),
            'models': {m: round(100 * v / cost_models, 1) for m, v in w['models'].items()} if cost_models else {},
            'by_pc': {pc: round(w['pcs'][pc]['cost_usd'], 2) if pc in w['pcs'] else 0 for pc in pcs},
        })
    # The computer with the highest usage sits at the bottom of the stack and gets the first color
    pcs.sort(key=lambda pc: -sum(r['by_pc'][pc] for r in rows))
    model_cost = collections.Counter()
    for k in keys:
        model_cost.update(weeks[k]['models'])
    # Models below 1 % of the total API-price equivalent are grouped
    minor = {m for m, v in model_cost.items() if v < 0.01 * sum(model_cost.values())}
    for r in rows:
        rest = sum(r['models'].pop(m) for m in minor if m in r['models'])
        if minor:
            r['models'][OTHERS] = round(rest, 1)
    models = sorted(set(model_cost) - minor, key=lambda m: -model_cost[m]) + ([OTHERS] if minor else [])
    full = [r for r in rows if r['full']]
    metrics = ('cost_usd', 'tokens', 'output', 'cache_write', 'cache_read', 'input')
    mean = {m: sum(r['total'][m] for r in full) / len(full) for m in metrics} if full else {}
    for r in rows:
        r['index'] = {m: round(100 * r['total'][m] / mean[m], 1) if mean.get(m) else None for m in metrics}
    # Trend over full weeks only, as an index (mean = 100), per week in percent
    slope, icpt = trend([r['index']['cost_usd'] for r in full])
    pos = {r['week']: i for i, r in enumerate(full)}
    # The current week right after the last full one: trend extended, not part of it
    if full and rows[-1]['running'] and not rows[-1]['full'] and len(rows) >= 2 and rows[-2] is full[-1]:
        pos[rows[-1]['week']] = len(full)
    for r in rows:
        r['trend'] = round(icpt + slope * pos[r['week']], 1) if r['week'] in pos else None
    spread = max(abs(r['index']['cost_usd'] - 100) for r in full) if full else 0
    # Quota: mean, band and trend over the weeks with a weekly-limit message
    est = [r for r in rows if r['quota'] and r['quota']['kind'] == 'hit']
    q_mean = sum(r['quota']['value'] for r in est) / len(est) if est else 0
    q_spread = max(abs(100 * r['quota']['value'] / q_mean - 100) for r in est) if est else 0
    q_slope, _ = trend([100 * r['quota']['value'] / q_mean for r in est]) if est else (0, 0)
    prev = est[:-1]
    prev_mean = sum(r['quota']['value'] for r in prev) / len(prev) if prev else 0
    # Band of the weeks before the last measurement, at least ±5 %: only against it can the latest
    # week fall outside (a band over all weeks contains every week)
    prev_spread = max(5, *(abs(100 * r['quota']['value'] / prev_mean - 100) for r in prev)) if len(prev) >= 2 else None
    last_dev = round(100 * est[-1]['quota']['value'] / prev_mean - 100, 1) if prev else None
    lower = [r for r in rows if r['quota'] and r['quota']['kind'] == 'min']
    data = {
        'pcs': [{'id': pc, 'name': pc} for pc in pcs], 'rows': rows,
        'models': [{'id': m, 'name': model_name(m)} for m in models],
        'mean_cost': round(mean.get('cost_usd', 0), 2), 'mean_tokens': mean.get('tokens', 0),
        'slope_pct': round(slope, 1), 'spread_pct': round(spread, 1), 'n_full': len(full),
        'quota': {
            'n': len(est), 'mean': round(q_mean, 2), 'spread_pct': round(q_spread, 1), 'slope_pct': round(q_slope, 1),
            'last': est[-1]['week'] if est else None,
            'last_dev_pct': last_dev,
            'prev_mean': round(prev_mean, 2), 'prev_spread_pct': round(prev_spread, 1) if prev_spread else None,
            'last_outside': abs(last_dev) > prev_spread if prev_spread else None,
            'max_lower': max(lower, key=lambda r: r['quota']['value'])['week'] if lower else None,
        },
        'week_reset': settings['reset_text'],
        'built': dt.date.today().isoformat(),
    }
    with open(os.path.join(HERE, 'theme.json'), encoding='utf-8') as fh:
        theme = fh.read()
    with open(os.path.join(HERE, 'template.html'), encoding='utf-8') as fh:
        html = fh.read()
    html = html.replace('/*THEME*/null', theme).replace('/*DATA*/null', json.dumps(data, ensure_ascii=False))
    out = os.path.join(HERE, 'report.html')
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write(html)
    print(f'{len(rows)} weeks, {len(full)} full, usage $ {data["mean_cost"]:.2f} per week on average (±{data["spread_pct"]} %)')
    for r in rows:
        q = r['quota']
        if q:
            print(f"  {r['week']}  quota {'≥ ' if q['kind'] == 'min' else ''}$ {q['value']:.2f}"
                  + (' (up to the weekly limit)' if q['kind'] == 'hit' else ' (no weekly limit hit)'))
        for c in r['checks']:
            print(f"  {r['week']}  Warning: {c}")
    if est:
        if prev_spread:
            print(f"Last measurement {last_dev:+.1f} % against the weeks before, "
                  f"{'OUTSIDE' if abs(last_dev) > prev_spread else 'inside'} their spread (±{prev_spread:.1f} %)")
        print(f'Quota $ {q_mean:.2f} on average over {len(est)} weeks, range ±{q_spread:.1f} %')
    print(f'-> {out}')


if __name__ == '__main__':
    main()
