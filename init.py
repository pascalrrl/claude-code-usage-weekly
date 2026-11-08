#!/usr/bin/env python3
"""Set up this folder: ask for your weekly reset and the name of this computer, write
settings.json, and optionally count the last 30 days and open the report.

    python3 init.py

Run it again at any time to check or change the settings; other entries of settings.json, like
the names of your other computers, are kept.
"""
import glob, json, os, pathlib, subprocess, sys, webbrowser

import prompts as ui
import scan_usage as su  # limit weeks and settings.json

SETTINGS = os.path.join(su.HERE, 'settings.json')
RETENTION = 60  # days of transcripts to keep, so that a scan every 4 weeks misses nothing


def local_tz_name():
    """IANA name of this computer's time zone if it can be found (macOS, Linux), else UTC."""
    tz = os.environ.get('TZ', '').lstrip(':')
    if '/' in tz:
        return tz
    path = os.path.realpath('/etc/localtime')
    return path.split('zoneinfo/', 1)[1] if 'zoneinfo/' in path else 'UTC'


def tz_error(name):
    try:
        su.timezone(name)
        return None
    except su.SettingsError as e:
        return str(e)


def ask_reset():
    while True:
        line = ui.text('When does your weekly limit reset?', hint='Paste the reset of the weekly limit from /usage in '
                       'Claude Code, e.g. "Resets Mar 12, 5pm (America/New_York)" – or press Enter to pick it step by step',
                       validate=lambda s: None if not s or su.parse_reset(s) else 'Could not read a date, a time and a time zone',
                       empty='step by step')
        if not line:
            break
        reset = su.parse_reset(line)
        if ui.confirm(f'Weekly reset {su.reset_text(reset)} – correct?'):
            return reset
    weekday = ui.select('Weekday of the reset', [(d, d.capitalize()) for d in su.WEEKDAYS])

    time = ui.text('Time of the reset (24-hour, HH:MM)', clean=lambda s: s.zfill(5),
                   validate=lambda s: None if su.parse_clock(s) else 'Use 24-hour time like 17:00')
    timezone = ui.text('Time zone', default=local_tz_name(), hint='IANA name like America/New_York, or UTC',
                       validate=tz_error)
    return {'weekday': weekday, 'time': time, 'timezone': timezone}


def retention_note():
    """Only a hint: this script does not change Claude Code's own settings."""
    path = os.path.join(os.path.expanduser('~'), '.claude', 'settings.json')
    try:
        with open(path, encoding='utf-8') as fh:
            days = json.load(fh).get('cleanupPeriodDays')
    except (OSError, ValueError, AttributeError):
        days = None
    if isinstance(days, int) and days >= RETENTION:
        ui.note(f'Claude Code keeps transcripts for {days} days', ['Run scan_usage.py at least every 4 weeks.'])
    else:
        ui.note(f'Claude Code keeps transcripts for {days or 30} days{"" if days else " (default)"}', [
            f'To keep them for {RETENTION} days, add this line inside the braces of',
            f'{path}:', '', f'    "cleanupPeriodDays": {RETENTION},', '',
            'Until then, run scan_usage.py at least every 2 weeks.'], warn=True)


def run(script):
    p = subprocess.run([sys.executable, os.path.join(su.HERE, script)],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return p.returncode == 0, p.stdout.splitlines()


def summary(lines):
    """Console output of the scripts, without paths, older-format warnings counted once."""
    old = sum('older format' in x for x in lines)
    out = [x.strip() for x in lines if x.strip() and not x.startswith('->') and 'older format' not in x]
    return out + ([f'{old} week {"file" if old == 1 else "files"} in an older format skipped'] if old else [])


def first_run():
    ok, lines = ui.task('Counting the last 30 days', lambda: run('scan_usage.py'))
    ui.note('Counted' if ok else 'Counting failed', summary(lines), warn=not ok)
    if not ok:
        return False
    ok, lines = ui.task('Building the report', lambda: run('build_report.py'))
    ui.note('Report built' if ok else 'Building the report failed', summary(lines), warn=not ok)
    if ok:
        webbrowser.open(pathlib.Path(su.HERE, 'report.html').as_uri())
    return ok


def main():
    ui.intro('claude-usage-weekly · setup')
    try:
        with open(SETTINGS, encoding='utf-8') as fh:
            settings = json.load(fh)
    except FileNotFoundError:
        settings = {}
    except ValueError as e:
        ui.outro(ui.red(f'settings.json is not valid JSON ({e}). Fix or delete it, then run init.py again.'))
        sys.exit(1)

    reset = settings.get('week_reset')
    if not (reset and ui.confirm(f'Keep the weekly reset {su.reset_text(reset)}?')):
        settings['week_reset'] = ask_reset()
        if reset and settings['week_reset'] != reset and glob.glob(os.path.join(su.HERE, 'data', '*', '*.json')):
            ui.note('The reset changed', ['The week files in data/ were cut with the old reset. Delete them',
                                          'and count again (scan_usage.py -t0 YYYY-MM-DD).'], warn=True)

    pc = su.default_pc()
    computers = settings.setdefault('computers', {})
    name = ui.text('Name of this computer in the report', default=computers.get(pc, pc),
                   hint=f'Its data folder is data/{pc}', validate=lambda s: None if s else 'Enter a name')
    if name == pc:
        computers.pop(pc, None)
    else:
        computers[pc] = name
    if not computers:
        settings.pop('computers')

    tmp = SETTINGS + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(settings, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, SETTINGS)
    try:
        su.load_settings()
    except su.SettingsError as e:
        ui.outro(ui.red(f'Saved settings.json, but it has an error: {e}. Run init.py again.'))
        sys.exit(1)
    ui.step('Saved settings.json', 'Names of other computers can be added there under "computers"')

    retention_note()

    if ui.confirm('Count the last 30 days on this computer and open the report?'):
        if not first_run():
            ui.outro(ui.red('Setup saved, but the first run failed – see above.'))
            sys.exit(1)
        ui.outro('Done. The report is open in your browser.')
    else:
        py = 'python' if os.name == 'nt' else 'python3'
        ui.outro(f'Done. Next time: {py} scan_usage.py, then {py} build_report.py')


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        sys.stdout.write(ui.SHOW if ui.FANCY else '')
        print('\nAborted.')
        sys.exit(1)
