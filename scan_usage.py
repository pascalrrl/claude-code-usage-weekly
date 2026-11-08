#!/usr/bin/env python3
"""Count this computer's Claude Code usage per limit week: one file per week.

    python3 scan_usage.py                                # weeks of the last 30 days up to today
    python3 scan_usage.py -t0 2026-10-01 -t1 2026-10-31  # every week touching this range

A limit week starts when the weekly limit resets, as set in settings.json ("week_reset"). Every
week touching the range is counted in full and written to data/<computer>/<start date>.json.
Counting a finished week again replaces only its file, unless the new count finds less than the
existing one (transcripts deleted in the meantime): then the existing file is kept.

A week file holds token counts per model and per hour and the limit messages, no dollar amounts:
build_report.py prices them with prices.json, so a corrected price applies to every week.

Reads ~/.claude/projects (Windows: %USERPROFILE%\\.claude\\projects). Python 3.9 or newer.
"""
import argparse, collections, datetime as dt, glob, json, os, re, sys

import common
from common import TOKEN_FIELDS, UTC, parse_ts

# "You've hit your weekly limit · resets Mar 12 at 5pm (America/New_York)", "… session limit …"
LIMIT_RE = re.compile(r"hit your ([\w ]+?) limit")


def iso(t):
    return t.isoformat(timespec='seconds').replace('+00:00', 'Z')


def date_arg(s):
    try:
        return common.parse_date(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f'not a valid date: {s} (format 2026-10-31)')


def dedupe(events):
    """The same message appears in several transcripts (session, subagent, parallel sessions):
    the same kind and text within 5 hours count once."""
    kept = []
    for t, kind, text in sorted(events):
        if not any(k == kind and x == text and t - s < dt.timedelta(hours=5) for s, k, x in kept):
            kept.append((t, kind, text))
    return kept


def scan(files, begin, end, settings):
    """Token counts per week, model and hour; limit messages; the oldest entry of all transcripts."""
    weeks = collections.defaultdict(lambda: collections.defaultdict(
        lambda: {'requests': 0, 'hourly': collections.defaultdict(lambda: [0] * len(TOKEN_FIELDS))}))
    events, seen, oldest = [], set(), None  # nothing is left before the oldest entry
    for f in files:
        scan_file = os.path.getmtime(f) >= begin.timestamp()
        with open(f, encoding='utf-8', errors='ignore') as fh:
            for line in fh:
                if oldest is None or not scan_file:
                    m = re.search(r'"timestamp":"([^"]+)"', line)
                    if m:
                        t = parse_ts(m[1])
                        oldest = t if oldest is None else min(oldest, t)
                        if not scan_file:
                            break
                if not scan_file or ('"usage"' not in line and 'hit your' not in line):
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not d.get('timestamp'):
                    continue
                t = parse_ts(d['timestamp'])
                oldest = t if oldest is None else min(oldest, t)
                if not begin <= t < end:
                    continue
                m = d.get('message') if isinstance(d.get('message'), dict) else {}
                if m.get('model') == '<synthetic>':
                    text = ''.join(c.get('text', '') for c in m.get('content') or [] if isinstance(c, dict))
                    hit = LIMIT_RE.search(text)
                    if hit:
                        events.append((t, hit[1].strip().lower(), text.strip()))
                    continue
                u = m.get('usage')
                if d.get('type') != 'assistant' or not u:
                    continue
                key = (m.get('id'), d.get('requestId'))
                if key in seen:
                    continue
                seen.add(key)
                cc = u.get('cache_creation') or {}
                if cc:
                    cw5 = cc.get('ephemeral_5m_input_tokens', 0) or 0
                    cw1h = cc.get('ephemeral_1h_input_tokens', 0) or 0
                else:
                    cw5, cw1h = u.get('cache_creation_input_tokens', 0) or 0, 0
                tokens = (u.get('input_tokens', 0) or 0, u.get('output_tokens', 0) or 0, cw5, cw1h,
                          u.get('cache_read_input_tokens', 0) or 0)
                w = common.week_start(t, settings)
                rec = weeks[w][m.get('model') or 'unknown']
                rec['requests'] += 1
                hour = rec['hourly'][int((t - w).total_seconds() // 3600)]
                for i, n in enumerate(tokens):
                    hour[i] += n
    return weeks, dedupe(events), oldest


def week_record(pc, w, w_end, now, models, hits, oldest):
    out = {}
    for name, v in sorted(models.items(), key=lambda kv: -kv[1]['requests']):
        hourly = {str(h): v['hourly'][h] for h in sorted(v['hourly'])}
        out[name] = {'requests': v['requests'],
                     **{f: sum(x[i] for x in hourly.values()) for i, f in enumerate(TOKEN_FIELDS)},
                     'hourly': hourly}
    return {
        'format': common.FORMAT, 'pc': pc, 'week_start': iso(w), 'week_end': iso(w_end),
        'scanned_at': iso(now), 'counted_until': iso(min(w_end, now)),
        'data_from': iso(oldest) if oldest else None,
        'requests': sum(v['requests'] for v in out.values()),
        'limit_hits': [{'t': iso(t), 'kind': kind, 'text': text} for t, kind, text in hits],
        'models': out,
    }


def dump(rec):
    """JSON with one line per hour instead of one line per number."""
    text = json.dumps(rec, indent=2, ensure_ascii=False)
    return re.sub(r'\[\s+([\d,\s]+?)\s+\]', lambda m: '[' + ', '.join(x.strip() for x in m[1].split(',')) + ']', text)


def priced(rec, prices):
    """$ of a week file at the prices of prices.json, and the models without a price."""
    total, unknown, start = 0.0, set(), parse_ts(rec['week_start'])
    for name, v in rec['models'].items():
        key = common.model_key(name, prices)
        for h, tokens in v['hourly'].items():
            rates = common.price_at(key, start + dt.timedelta(hours=int(h)), prices) if key else None
            if rates is None:
                unknown.add(name)
            else:
                total += common.cost(tokens, rates)
    return total, unknown


def main():
    home = os.path.expanduser('~')
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('-t0', '--from', dest='t0', type=date_arg, help='first day, YYYY-MM-DD (default: today - 30 days)')
    ap.add_argument('-t1', '--to', dest='t1', type=date_arg, help='last day, included, YYYY-MM-DD (default: today)')
    ap.add_argument('--pc', default=common.default_pc(),
                    help='name of this computer, also the data folder (default: host name, %(default)s)')
    ap.add_argument('--projects', default=os.path.join(home, '.claude', 'projects'),
                    help='Claude Code transcripts (default: %(default)s)')
    ap.add_argument('--force', action='store_true',
                    help='replace existing week files even if the new count finds less')
    a = ap.parse_args()
    try:
        settings = common.load_settings()
    except common.SettingsError as e:
        sys.exit(f'Error: {e}')
    now = dt.datetime.now(UTC)
    t1 = a.t1 or now.date()
    t0 = a.t0 or t1 - dt.timedelta(days=30)
    if t0 > t1:
        ap.error('-t0 is after -t1')

    tz = settings['tz']
    first = common.week_start(dt.datetime.combine(t0, dt.time(0), tz), settings)
    last = common.week_start(dt.datetime.combine(t1 + dt.timedelta(days=1), dt.time(0), tz) - dt.timedelta(seconds=1), settings)
    begin, end = first, min(common.week_end(last, settings), now)

    files = glob.glob(os.path.join(a.projects, '**', '*.jsonl'), recursive=True)
    weeks, events, oldest = scan(files, begin, end, settings)
    hits = collections.defaultdict(list)
    for t, kind, text in events:
        hits[common.week_start(t, settings)].append((t, kind, text))

    outdir = os.path.join(common.HERE, 'data', a.pc)
    os.makedirs(outdir, exist_ok=True)
    print(f'Computer {a.pc}, {len(files)} transcripts, oldest entry {oldest:%Y-%m-%d %H:%M} UTC' if oldest
          else f'Computer {a.pc}: no transcripts in {a.projects}')
    unknown = set()
    w = first
    while w <= last and w < now:
        w_end = common.week_end(w, settings)
        rec = week_record(a.pc, w, w_end, now, weeks.get(w, {}), hits[w], oldest)
        notes = []
        if w_end > now:
            notes.append(f'current week, counted until {now:%Y-%m-%d %H:%M} UTC')
        if oldest is None or oldest > w:
            notes.append('transcripts only from ' + (f'{oldest:%Y-%m-%d}' if oldest else '–'))
        label = f'{common.week_key(w, settings)} – {common.week_key(w_end, settings)}'
        path = os.path.join(outdir, common.week_key(w, settings) + '.json')
        try:
            with open(path, encoding='utf-8') as fh:
                old = json.load(fh)
        except (OSError, ValueError):
            old = None
        # A finished week gains no transcripts, it can only lose some (cleanupPeriodDays)
        covered = lambda r: bool(r.get('data_from')) and parse_ts(r['data_from']) <= w
        if (old and w_end <= now and not a.force
                and (rec['requests'] < old.get('requests', 0) or (covered(old) and not covered(rec)))):
            print(f'  {label}  kept the existing file: the new count finds less '
                  f'({rec["requests"]} instead of {old.get("requests", 0)} requests'
                  f'{"; " + "; ".join(notes) if notes else ""}); use --force to replace it anyway')
            w = w_end
            continue
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(dump(rec) + '\n')
        usd, missing = priced(rec, settings['prices'])
        unknown |= missing
        weekly = [h for h in rec['limit_hits'] if h['kind'] == 'weekly']
        others = len(rec['limit_hits']) - len(weekly)
        print(f'  {label}  {rec["requests"]:>7} requests  $ {usd:>9.2f}'
              + (f'  weekly limit {parse_ts(weekly[0]["t"]):%Y-%m-%d %H:%M} UTC' if weekly else '')
              + (f'  {others} other limit {"message" if others == 1 else "messages"}' if others else '')
              + (f'  ({"; ".join(notes)})' if notes else ''))
        w = w_end
    for name in sorted(unknown):
        print(f'  Warning: no price for {name} in prices.json, counted as $0. Add it and build the report again.')
    print(f'-> {outdir}')


if __name__ == '__main__':
    main()
