#!/usr/bin/env python3
"""Count this computer's Claude Code usage per limit week: one file per week.

    python3 scan_usage.py                                # weeks of the last 30 days up to today
    python3 scan_usage.py -t0 2026-10-01 -t1 2026-10-31  # every week touching this range
    python3 scan_usage.py --reset "thursday 17:00 America/New_York"   # without settings.json

This file runs on its own: copy it alone to another computer, run it there and copy the folder
data/<computer>/ it writes next to it to the computer that builds the report. It needs no other
file of this tool; without settings.json, --reset gives the weekly reset.

A limit week starts when the weekly limit resets ("week_reset" in settings.json, or --reset). Every
week touching the range is counted in full and written to data/<computer>/<start date>.json.
Counting a finished week again replaces only its file, unless the new count finds less than the
existing one (transcripts deleted in the meantime): then the existing file is kept.

A week file holds token counts per model and per hour and the limit messages, no dollar amounts:
build_report.py prices them with prices.json, so a corrected price applies to every week.

This file also defines the limit weeks and the week files for init.py and build_report.py, which
import them from here.

Reads ~/.claude/projects (Windows: %USERPROFILE%\\.claude\\projects). Python 3.9 or newer.
"""
import argparse, collections, datetime as dt, glob, json, os, re, socket, sys

HERE = os.path.dirname(os.path.abspath(__file__))
UTC = dt.timezone.utc
FORMAT = 1  # version of the week files; files of another version are skipped by the report
WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
# Token fields of a request, in this order in the hourly lists of a week file
TOKEN_FIELDS = ('input', 'output', 'cache_write_5m', 'cache_write_1h', 'cache_read')
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
# "resets Mar 12 at 5pm (America/New_York)", "Resets Mar 12, 5pm (…)", "resets 5pm (…)"
RESET_RE = re.compile(r'resets (?:([A-Za-z]{3}) (\d{1,2})(?:,| at) )?(\d{1,2})(?::(\d{2}))? ?([ap]m) \(([^)]+)\)', re.I)
# "You've hit your weekly limit · resets Mar 12 at 5pm (America/New_York)", "… session limit …"
LIMIT_RE = re.compile(r"hit your ([\w ]+?) limit")
# The same limit message (kind and text) within this time counts once: it appears in several
# transcripts (session, subagent, parallel sessions) and on several computers
HIT_WINDOW = dt.timedelta(hours=5)


class SettingsError(Exception):
    pass


# --- Settings and limit weeks (also used by init.py and build_report.py) ---

def default_pc():
    """Name of this computer and its data folder: the host name."""
    return socket.gethostname().split('.')[0].lower()


def parse_date(s):
    """'2026-10-31' -> date."""
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', s):
        raise ValueError(s)
    return dt.date.fromisoformat(s)


def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))


def parse_clock(s):
    """'17:00' -> time, None if it is not a 24-hour time."""
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', s)
    return dt.time(int(m[1]), int(m[2])) if m and int(m[1]) < 24 and int(m[2]) < 60 else None


def timezone(name):
    if name == 'UTC':
        return UTC
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        raise SettingsError(f'unknown time zone {name!r} (on Windows, time zones other than UTC need '
                            '"pip install tzdata")')


def read_json(path, hint=''):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SettingsError(f'{os.path.basename(path)} not found{hint}')
    except (OSError, ValueError) as e:
        raise SettingsError(f'cannot read {path}: {e}')


def reset_text(r):
    """{'weekday': 'thursday', 'time': '17:00', 'timezone': …} -> 'Thursday 17:00 America/New_York'."""
    return f'{r["weekday"].capitalize()} {r["time"]} {r.get("timezone", "UTC")}'


def parse_reset(text):
    """Weekly reset from 'thursday 17:00 America/New_York' or from the line /usage shows
    ('Resets Mar 12, 5pm (America/New_York)'): {'weekday', 'time', 'timezone'}, None if unreadable."""
    m = re.fullmatch(r'([A-Za-z]+)\s+(\d{1,2}:\d{2})(?:\s+(\S+))?', text.strip())
    if m and m[1].lower() in WEEKDAYS:
        clock = parse_clock(m[2])
        try:
            timezone(m[3] or 'UTC')
        except SettingsError:
            return None
        return {'weekday': m[1].lower(), 'time': f'{clock:%H:%M}', 'timezone': m[3] or 'UTC'} if clock else None
    if not text.lower().startswith('resets'):
        text = 'resets ' + text
    m = RESET_RE.search(text)
    r = reset_from_text(text, dt.datetime.now(UTC)) if m and m[1] else None
    return {'weekday': WEEKDAYS[r.weekday()], 'time': f'{r:%H:%M}', 'timezone': m[6]} if r else None


def load_settings(path=None, reset=None):
    """Read and check settings.json (your own, not in the repository). reset ({'weekday', 'time',
    'timezone'}, from --reset) replaces its week_reset; with reset, settings.json is optional.
    Returns a dict with 'weekday' (0 = Monday), 'time', 'tz', 'reset_text' and 'computers' (folder
    name -> display name)."""
    path = path or os.path.join(HERE, 'settings.json')
    if reset and not os.path.exists(path):
        s = {}
    else:
        s = read_json(path, ': run init.py first (python3 init.py)')
    r, where = (reset, '--reset') if reset else (s.get('week_reset') or {}, 'settings.json: week_reset')
    weekday = str(r.get('weekday', '')).lower()
    if weekday not in WEEKDAYS:
        raise SettingsError(f'{where}: the weekday must be one of {", ".join(WEEKDAYS)}')
    clock = parse_clock(str(r.get('time', '')))
    if not clock:
        raise SettingsError(f'{where}: the time must look like "17:00"')
    tz_name = r.get('timezone', 'UTC')
    try:
        tz = timezone(tz_name)
    except SettingsError as e:
        raise SettingsError(f'{where}: {e}')
    computers = s.get('computers') or {}
    if not isinstance(computers, dict) or not all(isinstance(v, str) for v in computers.values()):
        raise SettingsError('settings.json: computers must map folder names to display names')
    return {'weekday': WEEKDAYS.index(weekday), 'time': clock, 'tz': tz, 'computers': computers,
            'reset_text': reset_text({'weekday': weekday, 'time': f'{clock:%H:%M}', 'timezone': tz_name})}


def week_start(t, s):
    """Start (in UTC) of the limit week the moment t falls in."""
    local = t.astimezone(s['tz'])
    day = local.date() - dt.timedelta(days=(local.weekday() - s['weekday']) % 7)
    start = dt.datetime.combine(day, s['time'], s['tz'])
    if start > local:
        start = dt.datetime.combine(day - dt.timedelta(days=7), s['time'], s['tz'])
    return start.astimezone(UTC)


def week_end(start, s):
    """End of the limit week that begins at start: same local time a week later."""
    day = start.astimezone(s['tz']).date() + dt.timedelta(days=7)
    return dt.datetime.combine(day, s['time'], s['tz']).astimezone(UTC)


def week_key(start, s):
    """Name of a week: the local date of its start, e.g. '2026-10-04'."""
    return start.astimezone(s['tz']).date().isoformat()


def reset_from_text(text, t):
    """'resets Mar 12 at 5pm (America/New_York)' or 'resets 5pm (…)' -> moment, None if unknown."""
    m = RESET_RE.search(text)
    if not m:
        return None
    try:
        tz = timezone(m[6])
    except SettingsError:  # unknown zone, or no time zone data (Windows without tzdata)
        return None
    local = t.astimezone(tz)
    month = m[1].capitalize() if m[1] else None
    try:
        clock = dt.time(int(m[3]) % 12 + (12 if m[5].lower() == 'pm' else 0), int(m[4] or 0))
        day = dt.date(local.year, MONTHS.index(month) + 1, int(m[2])) if month else None
    except ValueError:  # not a month, day or time
        return None
    if day:
        if day < local.date():
            day = day.replace(year=day.year + 1)
    else:
        day = local.date()
        if dt.datetime.combine(day, clock, tz) <= local:
            day += dt.timedelta(days=1)
    return dt.datetime.combine(day, clock, tz)


# --- Counting ---

def iso(t):
    return t.isoformat(timespec='seconds').replace('+00:00', 'Z')


def date_arg(s):
    try:
        return parse_date(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f'not a valid date: {s} (format 2026-10-31)')


def reset_arg(s):
    r = parse_reset(s)
    if not r:
        raise argparse.ArgumentTypeError(f'cannot read the weekly reset {s!r}; use e.g. "thursday 17:00 America/New_York" '
                                         'or the line /usage shows, e.g. "Resets Mar 12, 5pm (America/New_York)"')
    return r


def dedupe(events):
    """The same message appears in several transcripts (session, subagent, parallel sessions):
    the same kind and text within HIT_WINDOW count once."""
    kept = []
    for t, kind, text in sorted(events):
        if not any(k == kind and x == text and t - s < HIT_WINDOW for s, k, x in kept):
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
                w = week_start(t, settings)
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
        'format': FORMAT, 'pc': pc, 'week_start': iso(w), 'week_end': iso(w_end),
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


def main():
    home = os.path.expanduser('~')
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('-t0', '--from', dest='t0', type=date_arg, help='first day, YYYY-MM-DD (default: today - 30 days)')
    ap.add_argument('-t1', '--to', dest='t1', type=date_arg, help='last day, included, YYYY-MM-DD (default: today)')
    ap.add_argument('--reset', type=reset_arg,
                    help='weekly reset, e.g. "thursday 17:00 America/New_York" (default: week_reset in settings.json)')
    ap.add_argument('--pc', default=default_pc(),
                    help='name of this computer, also the data folder (default: host name, %(default)s)')
    ap.add_argument('--projects', default=os.path.join(home, '.claude', 'projects'),
                    help='Claude Code transcripts (default: %(default)s)')
    ap.add_argument('--force', action='store_true',
                    help='replace existing week files even if the new count finds less')
    a = ap.parse_args()
    try:
        settings = load_settings(reset=a.reset)
    except SettingsError as e:
        if not a.reset and not os.path.exists(os.path.join(HERE, 'settings.json')):
            e = f'{e}, or pass the weekly reset, e.g. --reset "thursday 17:00 America/New_York"'
        sys.exit(f'Error: {e}')
    now = dt.datetime.now(UTC)
    t1 = a.t1 or now.date()
    t0 = a.t0 or t1 - dt.timedelta(days=30)
    if t0 > t1:
        ap.error('-t0 is after -t1')

    tz = settings['tz']
    first = week_start(dt.datetime.combine(t0, dt.time(0), tz), settings)
    last = week_start(dt.datetime.combine(t1 + dt.timedelta(days=1), dt.time(0), tz) - dt.timedelta(seconds=1), settings)
    begin, end = first, min(week_end(last, settings), now)

    files = glob.glob(os.path.join(a.projects, '**', '*.jsonl'), recursive=True)
    weeks, events, oldest = scan(files, begin, end, settings)
    hits = collections.defaultdict(list)
    for t, kind, text in events:
        hits[week_start(t, settings)].append((t, kind, text))

    outdir = os.path.join(HERE, 'data', a.pc)
    os.makedirs(outdir, exist_ok=True)
    print(f'Computer {a.pc}, {len(files)} transcripts, oldest entry {oldest:%Y-%m-%d %H:%M} UTC, '
          f'weekly reset {settings["reset_text"]}' if oldest
          else f'Computer {a.pc}: no transcripts in {a.projects}')
    w = first
    while w <= last and w < now:
        w_end = week_end(w, settings)
        rec = week_record(a.pc, w, w_end, now, weeks.get(w, {}), hits[w], oldest)
        notes = []
        if w_end > now:
            notes.append(f'current week, counted until {now:%Y-%m-%d %H:%M} UTC')
        if oldest is None or oldest > w:
            notes.append('transcripts only from ' + (f'{oldest:%Y-%m-%d}' if oldest else '–'))
        label = f'{week_key(w, settings)} – {week_key(w_end, settings)}'
        path = os.path.join(outdir, week_key(w, settings) + '.json')
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
        weekly = [h for h in rec['limit_hits'] if h['kind'] == 'weekly']
        others = len(rec['limit_hits']) - len(weekly)
        print(f'  {label}  {rec["requests"]:>7} requests'
              + (f'  weekly limit {parse_ts(weekly[0]["t"]):%Y-%m-%d %H:%M} UTC' if weekly else '')
              + (f'  {others} other limit {"message" if others == 1 else "messages"}' if others else '')
              + (f'  ({"; ".join(notes)})' if notes else ''))
        w = w_end
    print(f'-> {outdir}')


if __name__ == '__main__':
    main()
