#!/usr/bin/env python3
"""Start here: count this computer, build the report, or change the settings.

    python3 start.py

The first start asks for a name for this computer and your weekly reset and writes settings.json.
After that a menu offers to count this computer, to build the report, or the settings, and comes
back after each of them until you quit. scan_usage.py and
build_report.py still run on their own, without questions, e.g. for scheduled runs.

Runs on macOS, Linux and Windows with Python 3.9 or newer, standard library only.
"""
import json, os, pathlib, re, secrets, subprocess, sys, webbrowser

import build_report
import prompts as ui
import scan_usage as su  # limit weeks and settings.json

TITLE = 'claude-code-usage-weekly'
SETTINGS = os.path.join(su.HERE, 'settings.json')
RETENTION = 60  # days of transcripts to keep, so that a count every 4 weeks misses nothing
ACTIONS = [('count', 'Count this computer'), ('build', 'Build and open the report'), ('settings', 'Settings'), ('quit', 'Quit')]


TAGLINE = 'your weekly limit in API-price dollars'
CREDITS = 'by pascalrrl · MIT License'
URL = 'github.com/pascalrrl/claude-code-usage-weekly'
WEEK = [9, 15, 22, 31, 27, 19, 11]  # bar heights of the chart, in eighths of a line
PLAIN = ui.ASK == '>'  # the classic Windows console: ASCII frame and bars


def week_chart():
    """Seven bars, one per day of a week, four lines high."""
    blocks = ' ..::==##' if PLAIN else ' ▁▂▃▄▅▆▇█'
    return [' '.join(blocks[min(8, max(0, h - r * 8))] for h in WEEK) for r in range(3, -1, -1)]


def header():
    """The header of the main screen: a week chart, the title and the credits, framed (only in a terminal)."""
    if not ui.FANCY:
        ui.intro(TITLE)
        return
    width, (tl, tr, bl, br, h, v) = 68, '++++-|' if PLAIN else '╭╮╰╯─│'
    chart = week_chart()
    text = [(TITLE, ui.bold), (TAGLINE, str), ('', str), (CREDITS, ui.dim)]
    rows = [('', '')] + [(f'   {chart[i]}    {t}', f'   {ui.cyan(chart[i])}    {style(t)}') for i, (t, style) in enumerate(text)]
    rows += [(' ' * 20 + URL, ' ' * 20 + ui.dim(URL)), ('', '')]
    c = ui.cyan
    lines = ([c(tl + h * width + tr)] + [c(v) + styled + ' ' * (width - len(plain)) + c(v) for plain, styled in rows]
             + [c(bl + h * width + br)])
    print('\n' + '\n'.join(lines))


def screen(title, results=()):
    """A fresh screen (in a terminal) with the results of the last step on top."""
    ui.clear()
    header() if title == TITLE else ui.intro(title)
    for show in results:
        show()


# --- settings.json ---

def folder(settings):
    """Data folder of this computer: fixed in settings.json, the host name only before that."""
    return settings.get('folder') or su.default_pc()


def new_folder():
    """A new data folder: the host name and 4 random hex digits, e.g. macbook-pro-7f3e. The random
    part keeps two computers of the same host name (a new Mac is often just "macbook-pro") out of
    each other's folder: copied to one computer, one would overwrite the other's week files."""
    host = re.sub(r'[^a-z0-9._-]+', '-', su.default_pc()).strip('-._') or 'computer'
    return f'{host}-{secrets.token_hex(2)}'


def folders_of(name):
    """Folders in data/ that may be this computer's: the one of its host name, and those whose week
    files carry its name."""
    host = su.default_pc()
    found = {r['pc'] for _, r in build_report.week_files() if name and r.get('name') == name}
    if os.path.isdir(os.path.join(su.HERE, 'data', host)):
        found.add(host)
    return sorted(f for f in found if su.FOLDER_RE.fullmatch(f))


def migrate_folder(settings):
    """The folder for a settings.json of an older version, which counted into data/<host name>/:
    that folder if it exists, else the only one whose files carry this computer's name (the host
    name changed since), else a new one."""
    host = su.default_pc()
    if os.path.isdir(os.path.join(su.HERE, 'data', host)):
        return host
    mine = [f for f in folders_of(settings.get('name')) if f != host]
    return mine[0] if len(mine) == 1 else new_folder()


def ask_folder(settings):
    """First start: a new folder, unless data/ already holds one that may be this computer's (e.g.
    after settings.json was deleted). Then you choose: it may also be a copy from another computer."""
    new, found = new_folder(), folders_of(settings.get('name'))
    if not found:
        return new
    return ui.select('Data folder of this computer',
                     [(f, f'data/{f}', 'existing – if this computer counted into it before') for f in found]
                     + [(new, f'data/{new}', 'new – if the folder above is another computer\'s')])


def read_settings():
    try:
        with open(SETTINGS, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except ValueError as e:
        ui.outro(ui.red(f'settings.json is not valid JSON ({e}). Fix or delete it, then start again.'))
        sys.exit(1)


def save(settings):
    tmp = SETTINGS + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(settings, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, SETTINGS)
    try:
        su.load_settings()
    except su.SettingsError as e:
        ui.outro(ui.red(f'Saved settings.json, but it has an error: {e}. Start again to fix it.'))
        sys.exit(1)


def local_tz_name():
    """IANA name of this computer's time zone if it can be found (macOS, Linux), else UTC."""
    tz = os.environ.get('TZ', '').lstrip(':')
    if '/' in tz:
        return tz
    try:  # Debian, Ubuntu
        with open('/etc/timezone', encoding='utf-8') as fh:
            name = fh.read().strip()
            if '/' in name:
                return name
    except OSError:
        pass
    path = os.path.realpath('/etc/localtime')  # macOS, most Linux; Windows has neither
    return path.split('zoneinfo/', 1)[1] if 'zoneinfo/' in path else 'UTC'


def tz_error(name):
    try:
        su.timezone(name)
        return None
    except su.SettingsError as e:
        return str(e)


USAGE_HINT = 'In Claude Code, /usage shows it under the weekly limit, e.g. "Resets Mar 12, 5pm (America/New_York)"'


def paste_reset():
    """The weekly reset pasted from /usage; None for an empty answer."""
    line = ui.text('Paste the reset line from /usage', hint=USAGE_HINT, empty='nothing pasted', back=True,
                   validate=lambda s: None if not s or su.parse_reset(s) else 'Could not read a date, a time and a time zone in it')
    return su.parse_reset(line) if line else None


def ask_weekday(default='sunday', back=False):
    return ui.select('Weekday of the reset', [(d, d.capitalize()) for d in su.WEEKDAYS],
                     default=su.WEEKDAYS.index(default), back=back)


def ask_time(default=None):
    return ui.text('Time of the reset (24-hour, HH:MM)', default=default, clean=lambda s: s.zfill(5), back=True,
                   validate=lambda s: None if su.parse_clock(s) else 'Use 24-hour time like 17:00')


ZONE_REGIONS = ('Africa', 'America', 'Antarctica', 'Asia', 'Atlantic', 'Australia', 'Europe', 'Indian', 'Pacific')


def zone_names():
    """IANA zones like Europe/Berlin from Python's own time zone data (none on Windows without tzdata)."""
    try:
        from zoneinfo import available_timezones
        names = available_timezones()
    except Exception:
        return []
    return sorted(n for n in names if n.split('/', 1)[0] in ZONE_REGIONS and '/' in n)


def ask_timezone(default, back=False):
    """A list to filter by typing; without a terminal or time zone data, the name typed in."""
    zones = zone_names()
    if not ui.FANCY or not zones:
        return ui.text('Time zone', default=default, hint='IANA name like America/New_York, or UTC', validate=tz_error,
                       back=back)
    first = list(dict.fromkeys([default, local_tz_name(), 'UTC']))  # the current one, this computer's, UTC
    return ui.search('Time zone', first + [z for z in zones if z not in first], back=back,
                     hint='Type to filter, e.g. "new york" · ↑↓ choose · Enter takes it')


RESET_FIELDS = ('weekday', 'time', 'timezone')


def ask_field(field, r):
    """One part of the weekly reset r, starting from its current value; None if left with Back."""
    if field == 'weekday':
        return ask_weekday(r.get('weekday') or 'monday', back=True)
    if field == 'time':
        return ask_time(r.get('time'))
    return ask_timezone(r.get('timezone') or local_tz_name(), back=True)


def ask_reset(results):
    """First start: the weekly reset on one screen, like Settings – paste the line from /usage, or
    set weekday, time and time zone one by one; Done takes it and asks for what is still missing."""
    r, i = {'timezone': local_tz_name()}, 0
    while True:
        screen(TITLE, results)
        missing = [f for f in RESET_FIELDS if not r.get(f)]
        options = [('paste', 'Paste from /usage', 'sets all three at once'),
                   ('weekday', 'Weekday', r['weekday'].capitalize() if r.get('weekday') else '–'),
                   ('time', 'Time', r.get('time') or '–'),
                   ('timezone', 'Time zone', r.get('timezone') or '–'),
                   ('done', 'Done', su.reset_text(r) if not missing
                    else 'asks for the ' + ' and '.join(f.replace('timezone', 'time zone') for f in missing))]
        choice = ui.select('When does your weekly limit reset?', options, default=i, hint=USAGE_HINT, gap=len(options) - 1)
        try:
            if choice == 'paste':
                r = paste_reset() or r
            for f in (missing if choice == 'done' else [choice] if choice in RESET_FIELDS else []):
                value = ask_field(f, r)
                if not value:
                    break
                r[f] = value
        except ui.Back:  # Esc: back to this screen, nothing lost
            pass
        missing = [f for f in RESET_FIELDS if not r.get(f)]
        if choice == 'done' and not missing:
            return r
        # The cursor goes to the next value still missing, else to Done
        i = 1 + RESET_FIELDS.index(missing[0]) if missing else len(options) - 1


def ask_name(settings, back=False):
    pc = folder(settings)
    shown = (settings.get('computers') or {}).get(pc) or settings.get('name') or su.default_pc()
    where = f' in data/{pc}' if settings.get('folder') else ''
    return ui.text('Name of this computer in the report', default=shown, back=back,
                   hint=f'Saved with its data{where}, so the report shows it on every computer',
                   validate=lambda s: None if s.strip() else 'Enter a name').strip()


def transcript_days():
    """cleanupPeriodDays from Claude Code's own settings (None if not set) and that file's path."""
    path = os.path.join(os.path.expanduser('~'), '.claude', 'settings.json')
    try:
        with open(path, encoding='utf-8') as fh:
            days = json.load(fh).get('cleanupPeriodDays')
    except (OSError, ValueError, AttributeError):
        days = None
    return (days if isinstance(days, int) else None), path


def retention_note():
    """Only a hint: this tool does not change Claude Code's own settings."""
    days, path = transcript_days()
    if days is not None and days >= RETENTION:
        return lambda: ui.note(f'Claude Code keeps transcripts for {days} days',
                               ['Count this computer at least every 4 weeks.'])
    shown = f'{days} days' if days is not None else '30 days (default)'
    return lambda: ui.note(f'Claude Code keeps transcripts for {shown}', [
        f'To keep them for {RETENTION} days, add this line inside the braces of',
        f'{path}:', '', f'    "cleanupPeriodDays": {RETENTION},', '',
        'Until then, count this computer at least every 2 weeks.'], warn=True)


def retention_warning():
    """The retention note, only if transcripts may be deleted before the next count."""
    days, _ = transcript_days()
    return [] if days is not None and days >= RETENTION else [retention_note()]


def first_setup(settings):
    intro = lambda: ui.note('First start', ['Two questions – a name for this computer and your weekly',
                                            'reset –, then settings.json is written. You can change both',
                                            'later under Settings.'])
    while True:
        screen(TITLE, [intro])
        try:
            settings['name'] = ask_name(settings)
            break
        except ui.Back:  # Esc: the question again
            pass
    settings['week_reset'] = ask_reset([intro, lambda: ui.step('This computer', settings['name'])])
    settings['folder'] = ask_folder(settings)
    save(settings)
    return [lambda: ui.step('Saved settings.json', f'This computer {settings["name"]}, weekly reset '
                                                   f'{su.reset_text(settings["week_reset"])}'), retention_note()]


# --- Settings ---

def own_week_files(pc):
    """Week files this computer wrote, in its folder pc."""
    return [(rel, r) for rel, r in build_report.week_files() if r.get('pc') == pc and r.get('format') == su.FORMAT]


def rename_own_files(name, pc):
    """Put the new name into this computer's existing week files."""
    n = 0
    for rel, r in own_week_files(pc):
        if r.get('name') != name:
            r = {'format': r['format'], 'pc': r['pc'], 'name': name,
                 **{k: v for k, v in r.items() if k not in ('format', 'pc', 'name')}}
            with open(os.path.join(su.HERE, rel), 'w', encoding='utf-8') as fh:
                fh.write(su.dump(r) + '\n')
            n += 1
    return n


def change_reset(settings, results, ask):
    """Save the weekly reset that ask(old) returns (None: unchanged) and warn about old week files."""
    old = settings['week_reset']
    new = ask(old)
    if not new or new == old:
        return
    settings['week_reset'] = new
    save(settings)
    results.append(lambda: ui.step('Saved', f'Weekly reset {su.reset_text(new)}'))
    if list(build_report.week_files()):
        results.append(lambda: ui.note('The weekly reset changed', [
            'The week files in data/ were cut with the old reset; the report skips them now.',
            'Delete them and count again, on every computer (scan_usage.py -t0 YYYY-MM-DD).'], warn=True))


def change_other(settings, results, pc, from_data):
    """Rename another computer whose data was copied here; the name is kept in settings.json."""
    overrides = settings.get('computers', {})
    name = ui.text(f'Name of {pc} in the report', default=overrides.get(pc) or from_data[pc], back=True,
                   hint=f'Leave it empty to use the name from its data again: {from_data[pc]}').strip()
    if not name or name == from_data[pc]:
        overrides.pop(pc, None)
    else:
        overrides[pc] = name
    if overrides:
        settings['computers'] = overrides
    else:
        settings.pop('computers', None)
    save(settings)
    results.append(lambda: ui.step('Saved', f'{pc} is shown as {overrides.get(pc) or from_data[pc]}'))


def settings_menu(settings):
    """All settings on one screen with their values; Enter changes one, Back (or Esc) goes back."""
    results, last = [], 0
    while True:
        screen('Settings', results + retention_warning())
        reset, here = settings['week_reset'], folder(settings)
        from_data = build_report.computer_names({}, list(build_report.week_files()))
        overrides = settings.get('computers', {})
        options = [('name', 'This computer', overrides.get(here) or settings.get('name') or here)]
        options += [(('pc', pc), f'Computer {pc}', overrides.get(pc) or from_data[pc])
                    for pc in sorted(from_data) if pc != here]
        options += [('weekday', 'Weekday of the reset', reset['weekday'].capitalize()),
                    ('time', 'Time of the reset', reset['time']),
                    ('timezone', 'Time zone of the reset', reset['timezone']),
                    ('paste', 'Reset from /usage', 'paste the line to set all three')]
        choice = ui.select('What do you want to change?', options, default=min(last, len(options) - 1), back=True)
        if choice is None:
            return
        last = next(i for i, o in enumerate(options) if o[0] == choice)
        results = []
        try:
            if choice == 'weekday':
                change_reset(settings, results, lambda r: (d := ask_weekday(r['weekday'], back=True)) and {**r, 'weekday': d})
            elif choice == 'time':
                change_reset(settings, results, lambda r: {**r, 'time': ask_time(r['time'])})
            elif choice == 'timezone':
                change_reset(settings, results, lambda r: (z := ask_timezone(r['timezone'], back=True)) and {**r, 'timezone': z})
            elif choice == 'paste':
                change_reset(settings, results, lambda r: paste_reset())
            elif choice == 'name':
                settings['name'] = ask_name(settings, back=True)
                overrides.pop(here, None)  # the name in its week files counts again
                if not overrides:
                    settings.pop('computers', None)
                save(settings)
                n = rename_own_files(settings['name'], here)
                results.append(lambda: ui.step('Saved', f'This computer is shown as {settings["name"]}'
                                               + (f'; {n} week {"file" if n == 1 else "files"} renamed' if n else '')))
            else:
                change_other(settings, results, choice[1], from_data)
        except ui.Back:
            pass


# --- Count and build ---

def run(script):
    """Run a script of this tool; its output in UTF-8 (≥ and ± fail in a Windows code page)."""
    p = subprocess.run([sys.executable, os.path.join(su.HERE, script)], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                       encoding='utf-8', errors='replace')
    return p.returncode == 0, p.stdout.splitlines()


def summary(lines):
    """Console output of the scripts, without paths, older-format warnings counted once."""
    old = sum('older format' in x for x in lines)
    out = [x.strip() for x in lines if x.strip() and not x.startswith('->') and 'older format' not in x]
    return out + ([f'{old} week {"file" if old == 1 else "files"} in an older format skipped'] if old else [])


def count(settings):
    ok, lines = ui.task('Counting the last 30 days', lambda: run('scan_usage.py'))
    hint = [] if not ok else ['', f'The week files are in data/{folder(settings)}/. If another computer builds the',
                              'report, copy this folder there.']
    return [lambda: ui.note('Counted' if ok else 'Counting failed', summary(lines) + hint, warn=not ok)]


def build():
    ok, lines = ui.task('Building the report', lambda: run('build_report.py'))
    if ok:
        webbrowser.open(pathlib.Path(su.HERE, 'report.html').as_uri())
    return [lambda: ui.note('Report built and opened in your browser' if ok else 'Building the report failed',
                            summary(lines), warn=not ok)]


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')  # a Windows code page cannot show every character
    settings = read_settings()
    settings.pop('last_action', None)  # older versions kept the last menu choice; gone with the next save
    results = first_setup(settings) if not settings.get('week_reset') else []
    if not settings.get('folder'):  # set up by an older version: fix the folder now
        settings['folder'] = migrate_folder(settings)
        save(settings)
    while True:
        screen(TITLE, results)
        action = ui.select('What do you want to do?', ACTIONS)
        if action == 'quit':
            ui.outro('Bye.')
            return
        if action == 'settings':
            settings_menu(settings)
            results = []
            continue
        screen(TITLE)
        results = count(settings) if action == 'count' else build()


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        sys.stdout.write(ui.SHOW if ui.FANCY else '')
        print('\nAborted.')
        sys.exit(1)
