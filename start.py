#!/usr/bin/env python3
"""Start here: count this computer, build the report, or change the settings.

    python3 start.py

The first start asks for your weekly reset and a name for this computer and writes settings.json.
After that a menu offers to count this computer, to build the report, or the settings, and comes
back after each of them until you quit; it starts on your last choice. scan_usage.py and
build_report.py still run on their own, without questions, e.g. for scheduled runs.

Runs on macOS, Linux and Windows with Python 3.9 or newer, standard library only.
"""
import json, os, pathlib, subprocess, sys, webbrowser

import build_report
import prompts as ui
import scan_usage as su  # limit weeks and settings.json

TITLE = 'claude-code-usage-weekly'
SETTINGS = os.path.join(su.HERE, 'settings.json')
RETENTION = 60  # days of transcripts to keep, so that a count every 4 weeks misses nothing
ACTIONS = [('count', 'Count this computer'), ('build', 'Build and open the report'), ('settings', 'Settings'), ('quit', 'Quit')]


def screen(title, results=()):
    """A fresh screen (in a terminal) with the results of the last step on top."""
    ui.clear()
    ui.intro(title)
    for show in results:
        show()


# --- settings.json ---

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


def ask_name(settings):
    pc = su.default_pc()
    return ui.text('Name of this computer in the report', default=settings.get('name') or pc,
                   hint=f'Saved with its data in data/{pc}, so the report shows it on every computer',
                   validate=lambda s: None if s.strip() else 'Enter a name').strip()


def retention_note():
    """Only a hint: this tool does not change Claude Code's own settings."""
    path = os.path.join(os.path.expanduser('~'), '.claude', 'settings.json')
    try:
        with open(path, encoding='utf-8') as fh:
            days = json.load(fh).get('cleanupPeriodDays')
    except (OSError, ValueError, AttributeError):
        days = None
    if isinstance(days, int) and days >= RETENTION:
        return lambda: ui.note(f'Claude Code keeps transcripts for {days} days',
                               ['Count this computer at least every 4 weeks.'])
    return lambda: ui.note(f'Claude Code keeps transcripts for {days or 30} days{"" if days else " (default)"}', [
        f'To keep them for {RETENTION} days, add this line inside the braces of',
        f'{path}:', '', f'    "cleanupPeriodDays": {RETENTION},', '',
        'Until then, count this computer at least every 2 weeks.'], warn=True)


def first_setup(settings):
    screen(TITLE, [lambda: ui.note('First start', ['Two questions, then settings.json is written. You can change it',
                                                   'later under Settings.'])])
    settings['week_reset'] = ask_reset()
    settings['name'] = ask_name(settings)
    settings.setdefault('last_action', 'count')
    save(settings)
    return [lambda: ui.step('Saved settings.json', f'Weekly reset {su.reset_text(settings["week_reset"])}, '
                                                   f'this computer: {settings["name"]}'), retention_note()]


# --- Settings ---

def own_week_files():
    """Week files this computer wrote (its folder is named after the host)."""
    return [(rel, r) for rel, r in build_report.week_files()
            if r.get('pc') == su.default_pc() and r.get('format') == su.FORMAT]


def rename_own_files(name):
    """Put the new name into this computer's existing week files."""
    n = 0
    for rel, r in own_week_files():
        if r.get('name') != name:
            r = {'format': r['format'], 'pc': r['pc'], 'name': name,
                 **{k: v for k, v in r.items() if k not in ('format', 'pc', 'name')}}
            with open(os.path.join(su.HERE, rel), 'w', encoding='utf-8') as fh:
                fh.write(su.dump(r) + '\n')
            n += 1
    return n


def other_computers(settings):
    """Rename the other computers whose data was copied here; the names are kept in settings.json."""
    from_data = build_report.computer_names({}, list(build_report.week_files()))
    others = sorted(pc for pc in from_data if pc != su.default_pc())
    results = []
    while True:
        screen('Settings · names of other computers', results)
        overrides = settings.get('computers', {})
        options = [(pc, f'{overrides.get(pc) or from_data[pc]}  ({pc})') for pc in others] + [('back', 'Back')]
        pc = ui.select('Which computer?', options, hint='A name set here overrides the name its data carries')
        if pc == 'back':
            return
        name = ui.text(f'Name of {pc} in the report', default=overrides.get(pc) or from_data[pc],
                       hint=f'Enter "{from_data[pc]}" to use the name from its data again').strip()
        if not name or name == from_data[pc]:
            overrides.pop(pc, None)
        else:
            overrides[pc] = name
        if overrides:
            settings['computers'] = overrides
        else:
            settings.pop('computers', None)
        save(settings)
        shown = overrides.get(pc) or from_data[pc]
        results = [lambda: ui.step('Saved', f'{pc} is shown as {shown}')]


def settings_menu(settings):
    results = []
    while True:
        screen('Settings', results)
        files = list(build_report.week_files())
        others = [pc for pc in build_report.computer_names(settings, files) if pc != su.default_pc()]
        options = [('reset', f'Weekly reset: {su.reset_text(settings["week_reset"])}'),
                   ('name', f'Name of this computer: {settings.get("name") or su.default_pc()}')]
        options += [('others', f'Names of other computers ({len(others)})')] if others else []
        options += [('retention', 'How long Claude Code keeps transcripts'), ('back', 'Back')]
        choice = ui.select('What do you want to change?', options)
        results = []
        if choice == 'back':
            return
        if choice == 'reset':
            screen('Settings · weekly reset')
            old = settings['week_reset']
            settings['week_reset'] = ask_reset()
            save(settings)
            results = [lambda: ui.step('Saved', f'Weekly reset {su.reset_text(settings["week_reset"])}')]
            if settings['week_reset'] != old and files:
                results.append(lambda: ui.note('The weekly reset changed', [
                    'The week files in data/ were cut with the old reset; the report skips them now.',
                    'Delete them and count again, on every computer (scan_usage.py -t0 YYYY-MM-DD).'], warn=True))
        elif choice == 'name':
            screen('Settings · name of this computer')
            settings['name'] = ask_name(settings)
            save(settings)
            n = rename_own_files(settings['name'])
            results = [lambda: ui.step('Saved', f'This computer is shown as {settings["name"]}'
                                       + (f'; {n} week {"file" if n == 1 else "files"} renamed' if n else ''))]
        elif choice == 'others':
            other_computers(settings)
        elif choice == 'retention':
            results = [retention_note()]


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


def count():
    ok, lines = ui.task('Counting the last 30 days', lambda: run('scan_usage.py'))
    hint = [] if not ok else ['', f'The week files are in data/{su.default_pc()}/. If another computer builds the',
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
    results = first_setup(settings) if not settings.get('week_reset') else []
    while True:
        screen(TITLE, results)
        last = next((i for i, (a, _) in enumerate(ACTIONS) if a == settings.get('last_action')), 0)
        action = ui.select('What do you want to do?', ACTIONS, default=last)
        if action == 'quit':
            ui.outro('Bye.')
            return
        if action == 'settings':
            settings_menu(settings)
            results = []
            continue
        settings['last_action'] = action
        save(settings)
        screen(TITLE)
        results = count() if action == 'count' else build()


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        sys.stdout.write(ui.SHOW if ui.FANCY else '')
        print('\nAborted.')
        sys.exit(1)
