"""A small terminal UI for init.py, standard library only.

In a terminal it draws a step rail with colors, arrow-key menus, yes/no toggles and a spinner
(macOS and Linux via termios, Windows via msvcrt). Without a terminal (a pipe, some IDE consoles)
or with NO_COLOR set, it falls back to plain questions, so input can still be piped in.
"""
import os, sys, threading, time

FANCY = sys.stdin.isatty() and sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'
if FANCY and os.name == 'nt':
    os.system('')  # switches the Windows console to ANSI escape sequences


def _style(code):
    return lambda s: f'\x1b[{code}m{s}\x1b[0m' if FANCY else str(s)


bold, dim, gray, cyan, green, yellow, red = (_style(c) for c in ('1', '2', '90', '36', '32', '33', '31'))
BAR = gray('│')
HIDE, SHOW = '\x1b[?25l', '\x1b[?25h'


def _out(s=''):
    sys.stdout.write(s)
    sys.stdout.flush()


def _clear(lines):
    """Move to the start of the line `lines` lines up and clear everything below."""
    _out(f'\x1b[{lines}F\x1b[J' if lines else '\r\x1b[J')


def _key():
    """One key press: 'up', 'down', 'left', 'right', 'enter', 'tab', or the character."""
    if os.name == 'nt':
        import msvcrt
        c = msvcrt.getwch()
        if c in ('\x00', '\xe0'):
            return {'H': 'up', 'P': 'down', 'K': 'left', 'M': 'right'}.get(msvcrt.getwch(), '')
    else:
        import select, termios, tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            c = os.read(fd, 1).decode(errors='ignore')
            if c == '\x1b' and select.select([fd], [], [], 0.05)[0]:
                seq = os.read(fd, 2).decode(errors='ignore')
                return {'[A': 'up', '[B': 'down', '[C': 'right', '[D': 'left'}.get(seq, '')
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if c == '\x03':
        raise KeyboardInterrupt
    if c == '\x04':
        raise EOFError
    return {'\r': 'enter', '\n': 'enter', '\t': 'tab'}.get(c, c)


def _done(label, value):
    _out(f'{BAR}\n{green("◇")}  {label}\n{BAR}  {dim(value)}\n')


def intro(title):
    _out(f'\n{gray("┌")}  {bold(title)}\n' if FANCY else f'{title}\n\n')


def outro(text):
    _out(f'{BAR}\n{gray("└")}  {text}\n\n' if FANCY else f'\n{text}\n')


def step(label, value):
    """A finished step without a question, e.g. a saved file."""
    _done(label, value) if FANCY else _out(f'{label}: {value}\n')


def note(title, lines, warn=False):
    if not FANCY:
        _out('\n' + title + '\n' + ''.join(f'  {x}\n' for x in lines))
        return
    mark = yellow('▲') if warn else cyan('●')
    _out(f'{BAR}\n{mark}  {title}\n' + ''.join(f'{BAR}  {dim(x)}\n' for x in lines))


def text(label, default=None, hint=None, validate=None, clean=None, empty='–'):
    """Free text; Enter takes the default. validate(value) returns an error message or None;
    clean(value) normalizes a valid answer; empty is shown for an empty answer."""
    error = None
    while True:
        if FANCY:
            lines = [BAR, f'{cyan("◆")}  {label}'] + ([f'{BAR}  {dim(hint)}'] if hint else [])
            lines += [f'{BAR}  {yellow("▲ " + error)}'] if error else []
            prompt = f'{BAR}  {cyan("›")} ' + (dim(f'({default}) ') if default else '')
            _out('\n'.join(lines) + '\n')
            value = input(prompt).strip() or default or ''
            _clear(len(lines) + 1)
        else:
            if error:
                _out(f'  {error}\n')
            value = input(f'{label}' + (f' [{default}]' if default else '') + ': ').strip() or default or ''
        error = validate(value) if validate else None
        if error is None:
            value = clean(value) if clean else value
            if FANCY:
                _done(label, value or empty)
            return value


def confirm(label, default=True):
    """Yes or no: arrow keys, Tab, y or n, then Enter."""
    if not FANCY:
        while True:
            answer = input(f'{label} [{"Y/n" if default else "y/N"}]: ').strip().lower()
            if not answer:
                return default
            if answer in ('y', 'yes', 'n', 'no'):
                return answer.startswith('y')
    value = default
    _out(f'{HIDE}{BAR}\n{cyan("◆")}  {label}\n')
    try:
        while True:
            yes_no = (f'{green("●")} Yes {gray("/")} {dim("○ No")}' if value
                      else f'{dim("○ Yes")} {gray("/")} {green("●")} No')
            _out(f'\r\x1b[K{BAR}  {yes_no}')
            k = _key()
            if k == 'enter':
                break
            if k in ('left', 'right', 'up', 'down', 'tab', ' '):
                value = not value
            elif k.lower() in ('y', 'n'):
                value = k.lower() == 'y'
                break
    finally:
        _out(SHOW)
    _clear(2)
    _done(label, 'Yes' if value else 'No')
    return value


def select(label, options, default=0, hint=None):
    """One of options (a list of (value, text)): arrow keys, then Enter."""
    if not FANCY:
        _out(f'{label}\n' + ''.join(f'  {i + 1}) {t}\n' for i, (_, t) in enumerate(options)))
        while True:
            answer = input(f'Choose 1–{len(options)} [{default + 1}]: ').strip()
            if not answer:
                return options[default][0]
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return options[int(answer) - 1][0]
    i, n = default, len(options)
    head = [BAR, f'{cyan("◆")}  {label}'] + ([f'{BAR}  {dim(hint)}'] if hint else [])
    _out(HIDE + '\n'.join(head) + '\n')
    try:
        while True:
            _out('\n'.join(f'{BAR}  ' + (f'{green("●")} {t}' if j == i else dim(f'○ {t}'))
                           for j, (_, t) in enumerate(options)))
            k = _key()
            if k == 'enter':
                break
            if k in ('up', 'k'):
                i = (i - 1) % n
            elif k in ('down', 'j', 'tab'):
                i = (i + 1) % n
            _clear(n - 1)
    finally:
        _out(SHOW)
    _clear(n - 1 + len(head))
    _done(label, options[i][1])
    return options[i][0]


def task(label, fn):
    """Run fn() with a spinner; returns its result."""
    if not FANCY:
        _out(f'{label} …\n')
        return fn()
    stop = threading.Event()

    def spin():
        frames = '◒◐◓◑'
        j = 0
        while not stop.wait(0.12):
            _out(f'\r\x1b[K{cyan(frames[j % 4])}  {label} …')
            j += 1

    _out(f'{HIDE}{BAR}\n{cyan("◒")}  {label} …')
    t = threading.Thread(target=spin, daemon=True)
    t.start()
    try:
        return fn()
    finally:
        stop.set()
        t.join()
        _out(f'\r\x1b[K\x1b[1F\x1b[J{SHOW}')
