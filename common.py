"""Shared by init.py, scan_usage.py and build_report.py: settings.json, prices.json, limit weeks and
prices."""
import datetime as dt, json, os, re, socket

HERE = os.path.dirname(os.path.abspath(__file__))
UTC = dt.timezone.utc
FORMAT = 1  # version of the week files; files of another version are skipped by the report
WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
# Token fields of a request, in this order in the hourly lists of a week file
TOKEN_FIELDS = ('input', 'output', 'cache_write_5m', 'cache_write_1h', 'cache_read')
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
# "resets Mar 12 at 5pm (America/New_York)", "Resets Mar 12, 5pm (…)", "resets 5pm (…)"
RESET_RE = re.compile(r'resets (?:([A-Za-z]{3}) (\d{1,2})(?:,| at) )?(\d{1,2})(?::(\d{2}))? ?([ap]m) \(([^)]+)\)', re.I)


class SettingsError(Exception):
    pass


def default_pc():
    """Name of this computer and its data folder: the host name."""
    return socket.gethostname().split('.')[0].lower()


def parse_date(s):
    """'2026-10-31' -> date. Used by argparse."""
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', s):
        raise ValueError(s)
    return dt.date.fromisoformat(s)


def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))


def _timezone(name):
    if name == 'UTC':
        return UTC
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        raise SettingsError(f'settings.json: unknown time zone {name!r} (on Windows, time zones other than UTC need '
                            '"pip install tzdata")')


def _day(v, where):
    if v is None:
        return None
    try:
        return dt.datetime.combine(parse_date(v), dt.time(0), UTC)
    except (TypeError, ValueError):
        raise SettingsError(f'{where}: {v!r} is not a date like 2026-10-31')


def _read(path, hint=''):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SettingsError(f'{os.path.basename(path)} not found{hint}')
    except (OSError, ValueError) as e:
        raise SettingsError(f'cannot read {path}: {e}')


def load_prices(path=None):
    """Read and check prices.json: {model: [(from, until, rates), ...]} sorted by 'from'."""
    prices = {}
    for model, periods in _read(path or os.path.join(HERE, 'prices.json')).items():
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


def load_settings(path=None, prices_path=None):
    """Read and check settings.json (your own, not in the repository) and prices.json. Returns a dict
    with 'weekday' (0 = Monday), 'time', 'tz', 'reset_text', 'computers' (folder name -> display
    name) and 'prices' (see load_prices)."""
    s = _read(path or os.path.join(HERE, 'settings.json'),
              ': run init.py first (python3 init.py)')
    r = s.get('week_reset') or {}
    weekday = str(r.get('weekday', '')).lower()
    if weekday not in WEEKDAYS:
        raise SettingsError(f'settings.json: week_reset.weekday must be one of {", ".join(WEEKDAYS)}')
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', str(r.get('time', '')))
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        raise SettingsError('settings.json: week_reset.time must look like "17:00"')
    tz_name = r.get('timezone', 'UTC')
    computers = s.get('computers') or {}
    if not isinstance(computers, dict) or not all(isinstance(v, str) for v in computers.values()):
        raise SettingsError('settings.json: computers must map folder names to display names')
    return {
        'weekday': WEEKDAYS.index(weekday), 'time': dt.time(int(m[1]), int(m[2])), 'tz': _timezone(tz_name),
        'reset_text': f'{weekday.capitalize()} {int(m[1]):02d}:{m[2]} {tz_name}', 'computers': computers,
        'prices': load_prices(prices_path),
    }


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


def reset_from_text(text, t):
    """'resets Mar 12 at 5pm (America/New_York)' or 'resets 5pm (…)' -> moment, None if unknown."""
    m = RESET_RE.search(text)
    if not m:
        return None
    try:
        tz = _timezone(m[6])
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
