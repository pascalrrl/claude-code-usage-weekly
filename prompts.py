"""A small terminal UI for start.py, standard library only.

In a terminal it draws a step rail with colors, arrow-key menus, yes/no toggles and a spinner
(macOS and Linux via termios, Windows via msvcrt). The classic Windows console gets plain
symbols, as its fonts lack some of the others; Windows Terminal gets the full set. Without a
terminal (a pipe, some IDE consoles) or with NO_COLOR set, it falls back to plain questions, so
input can still be piped in. In a terminal, Esc leaves a question by raising Back (in select only
with back=True).
"""
import os, shutil, sys, threading

FANCY = sys.stdin.isatty() and sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'
if FANCY and os.name == 'nt':
    os.system('')  # switches the Windows console to ANSI escape sequences
# Symbols: question, answered, selected, not selected, warning, info, spinner frames, input arrow
if os.name == 'nt' and not os.environ.get('WT_SESSION'):
    ASK, DONE, ON, OFF, WARN, INFO, SPIN, ARROW = '>', '+', '(*)', '( )', '!', 'i', '|/-\\', '>'
else:
    ASK, DONE, ON, OFF, WARN, INFO, SPIN, ARROW = '◆', '◇', '●', '○', '▲', '●', '◒◐◓◑', '›'


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


class Back(Exception):
    """Esc: the question is left without an answer."""


ESCAPES = {'[A': 'up', '[B': 'down', '[C': 'right', '[D': 'left', 'OA': 'up', 'OB': 'down', 'OC': 'right',
           'OD': 'left', '[H': 'home', '[F': 'end', 'OH': 'home', 'OF': 'end', '[1~': 'home', '[4~': 'end',
           '[3~': 'delete'}


def _key():
    """One key press: 'up', 'down', 'left', 'right', 'home', 'end', 'delete', 'backspace', 'clear',
    'enter', 'tab', 'esc', or the character."""
    if os.name == 'nt':
        import msvcrt
        c = msvcrt.getwch()
        if c in ('\x00', '\xe0'):
            return {'H': 'up', 'P': 'down', 'K': 'left', 'M': 'right', 'G': 'home', 'O': 'end',
                    'S': 'delete'}.get(msvcrt.getwch(), '')
    else:
        import select, termios, tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd, termios.TCSANOW)  # TCSAFLUSH, the default, would drop keys typed or pasted ahead
            b = os.read(fd, 1)
            if b == b'\x1b':  # Esc alone, or the start of an arrow or other special key
                seq = b''
                while len(seq) < 8 and select.select([fd], [], [], 0.05)[0]:
                    seq += os.read(fd, 1)
                    if len(seq) >= 2 and (seq[-1:].isalpha() or seq[-1:] == b'~'):
                        break
                if seq:
                    return ESCAPES.get(seq.decode(errors='ignore'), '')
            elif b and b[0] >= 0xc0:  # the rest of a UTF-8 character such as ä
                b += os.read(fd, 1 if b[0] < 0xe0 else 2 if b[0] < 0xf0 else 3)
            c = b.decode(errors='ignore')
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if c == '\x03':
        raise KeyboardInterrupt
    if c == '\x04':
        raise EOFError
    return {'\r': 'enter', '\n': 'enter', '\t': 'tab', '\x1b': 'esc', '\x7f': 'backspace', '\x08': 'backspace',
            '\x01': 'home', '\x05': 'end', '\x15': 'clear'}.get(c, c)


def _edit(prompt, value, back=False):
    """A one-line editor that starts with value: arrow keys, Home, End, Backspace, Delete, Ctrl-U;
    Enter returns the line, Esc raises Back. With back, a button Back sits below it after an empty
    line, as in select: Down or Tab moves to it, Up or typing goes back to the line, Enter on it
    raises Back."""
    buf, pos, on_back = list(value), len(value), False

    def back_row():  # the button two lines down; the cursor returns to the start of the input line
        _out(f'\x1b[2E\x1b[K{BAR}  ' + (f'{green(ON)} Back' if on_back else dim(f'{OFF} Back')) + '\x1b[2F')

    if back:
        _out(f'\n{BAR}\n\x1b[2F')  # room for the empty line and the button
        back_row()
    try:
        while True:
            width = max(10, shutil.get_terminal_size().columns - 6)  # the prompt "│  › " takes 5
            off = max(0, pos - width)  # a long line scrolls instead of wrapping
            shown = ''.join(buf[off:off + width])
            left = 0 if on_back else len(shown) - (pos - off)
            _out((HIDE if on_back else SHOW) + f'\r\x1b[K{prompt}{shown}' + (f'\x1b[{left}D' if left else ''))
            k = _key()
            if k == 'esc' or (k == 'enter' and on_back):
                _out('\n')
                raise Back
            if k == 'enter':
                _out('\n')
                return ''.join(buf).strip()
            if back and k in ('down', 'up', 'tab'):
                on_back = not on_back if k == 'tab' else k == 'down'
                back_row()
                continue
            if on_back:  # typing on the button goes back to the line
                if not (len(k) == 1 and k.isprintable()) and k not in ('backspace', 'delete', 'clear'):
                    continue
                on_back = False
                back_row()
            if k == 'left':
                pos = max(0, pos - 1)
            elif k == 'right':
                pos = min(len(buf), pos + 1)
            elif k == 'home':
                pos = 0
            elif k == 'end':
                pos = len(buf)
            elif k == 'backspace' and pos:
                del buf[pos - 1]
                pos -= 1
            elif k == 'delete' and pos < len(buf):
                del buf[pos]
            elif k == 'clear':
                buf, pos = [], 0
            elif len(k) == 1 and k.isprintable():
                buf.insert(pos, k)
                pos += 1
    finally:
        _out(SHOW)


def _done(label, value):
    _out(f'{BAR}\n{green(DONE)}  {label}\n{BAR}  {dim(value)}\n')


def clear():
    """Empty the screen (only in a terminal)."""
    if FANCY:
        _out('\x1b[2J\x1b[H')


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
    mark = yellow(WARN) if warn else cyan(INFO)
    _out(f'{BAR}\n{mark}  {title}\n' + ''.join(f'{BAR}  {dim(x)}\n' for x in lines))


def text(label, default=None, hint=None, validate=None, clean=None, empty='–', back=False):
    """Free text. In a terminal the default is already typed in and can be edited, Esc raises
    Back, and with back a button Back below the line does too; without one, Enter takes the default. validate(value) returns an error message or None;
    clean(value) normalizes a valid answer; empty is shown for an empty answer."""
    error, value = None, default or ''
    while True:
        if FANCY:
            lines = [BAR, f'{cyan(ASK)}  {label}'] + ([f'{BAR}  {dim(hint)}'] if hint else [])
            lines += [f'{BAR}  {yellow(WARN + " " + error)}'] if error else []
            _out('\n'.join(lines) + '\n')
            try:
                value = _edit(f'{BAR}  {cyan(ARROW)} ', value, back)
            finally:
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
    """Yes or no: arrow keys, Tab, y or n, then Enter; Esc raises Back."""
    if not FANCY:
        while True:
            answer = input(f'{label} [{"Y/n" if default else "y/N"}]: ').strip().lower()
            if not answer:
                return default
            if answer in ('y', 'yes', 'n', 'no'):
                return answer.startswith('y')
    value = default
    _out(f'{HIDE}{BAR}\n{cyan(ASK)}  {label}\n')
    try:
        while True:
            yes_no = (f'{green(ON)} Yes {gray("/")} {dim(OFF + " No")}' if value
                      else f'{dim(OFF + " Yes")} {gray("/")} {green(ON)} No')
            _out(f'\r\x1b[K{BAR}  {yes_no}')
            k = _key()
            if k == 'esc':
                _clear(2)
                raise Back
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


def select(label, options, default=0, hint=None, back=False, gap=None):
    """One of options, a list of (value, text) or (value, text, detail): arrow keys, then Enter.
    The details form a second column. With back, a last entry Back (or Esc) returns None. An empty
    line comes before the option at index gap (with back and no gap: before Back), so that buttons
    like Back or Done do not look like one more choice."""
    options = list(options) + [(None, 'Back')] * back
    if gap is None and back:
        gap = len(options) - 1
    width = max((len(o[1]) for o in options if len(o) > 2), default=0)
    rows = [o[1].ljust(width) + '  ' + o[2] if len(o) > 2 else o[1] for o in options]
    i, n = default, len(options)
    lines = n + (gap is not None)  # drawn lines of the options
    if not FANCY:
        _out(f'{label}\n' + ''.join(('\n' if j == gap else '') + f'  {j + 1}) {t}\n' for j, t in enumerate(rows)))
        while True:
            answer = input(f'Choose 1–{n} [{default + 1}]: ').strip()
            if not answer:
                return options[default][0]
            if answer.isdigit() and 1 <= int(answer) <= n:
                return options[int(answer) - 1][0]
    head = [BAR, f'{cyan(ASK)}  {label}'] + ([f'{BAR}  {dim(hint)}'] if hint else [])
    _out(HIDE + '\n'.join(head) + '\n')
    try:
        while True:
            _out('\n'.join((f'{BAR}\n' if j == gap else '') + f'{BAR}  '
                            + (green(ON) + ' ' + (f'{o[1].ljust(width)}  {dim(o[2])}' if len(o) > 2 else o[1])
                               if j == i else dim(f'{OFF} {rows[j]}')) for j, o in enumerate(options)))
            k = _key()
            if k == 'enter':
                break
            if k == 'esc' and back:
                i = n - 1
                break
            if k in ('up', 'k'):
                i = (i - 1) % n
            elif k in ('down', 'j', 'tab'):
                i = (i + 1) % n
            _clear(lines - 1)
    finally:
        _out(SHOW)
    _clear(lines - 1 + len(head))
    if options[i][0] is None:
        return None
    _done(label, options[i][1])
    return options[i][0]


def search(label, options, hint=None, back=False, rows=8):
    """One of a long list of names: typing filters it (spaces match _), arrow keys choose, Enter
    takes it. With back, a last entry Back (or Esc) returns None. Needs a terminal (FANCY)."""
    def key(s):
        return s.lower().replace('_', ' ')
    query, i, drawn = '', 0, 0
    _out(HIDE)
    try:
        while True:
            matches = [o for o in options if key(query) in key(o)] if query else list(options)
            choices = matches + [None] * back
            i = min(i, max(len(choices) - 1, 0))
            top = min(max(0, i - rows + 1), max(0, len(matches) - rows))  # scroll the window to i
            lines = [BAR, f'{cyan(ASK)}  {label}'] + ([f'{BAR}  {dim(hint)}'] if hint else [])
            lines.append(f'{BAR}  {cyan(ARROW)} {query}\x1b[7m \x1b[0m')
            for j in range(top, min(top + rows, len(matches))):
                lines.append(f'{BAR}  ' + (f'{green(ON)} {matches[j]}' if j == i else dim(f'{OFF} {matches[j]}')))
            if not matches:
                lines.append(f'{BAR}  {dim("No match")}')
            more = len(matches) - min(top + rows, len(matches))
            if top or more:
                lines.append(f'{BAR}  ' + dim(f'{top} above · {more} below'))
            if back:
                lines.append(BAR)  # Back is a button, not one more choice
                lines.append(f'{BAR}  ' + (f'{green(ON)} Back' if i == len(matches) else dim(f'{OFF} Back')))
            _clear(drawn - 1) if drawn else None
            _out('\n'.join(lines))
            drawn = len(lines)
            k = _key()
            if k == 'enter' and choices:
                break
            if k == 'esc' and back:
                i = len(choices) - 1
                break
            if k == 'up' and choices:
                i = (i - 1) % len(choices)
            elif k in ('down', 'tab') and choices:
                i = (i + 1) % len(choices)
            elif k == 'backspace':
                query, i = query[:-1], 0
            elif k == 'clear':
                query, i = '', 0
            elif len(k) == 1 and k.isprintable():
                query, i = query + k, 0
    finally:
        _out(SHOW)
    _clear(drawn - 1)
    if choices[i] is None:
        return None
    _done(label, choices[i])
    return choices[i]


def task(label, fn):
    """Run fn() with a spinner; returns its result."""
    if not FANCY:
        _out(f'{label} …\n')
        return fn()
    stop = threading.Event()

    def spin():
        j = 0
        while not stop.wait(0.12):
            _out(f'\r\x1b[K{cyan(SPIN[j % len(SPIN)])}  {label} …')
            j += 1

    _out(f'{HIDE}{BAR}\n{cyan(SPIN[0])}  {label} …')
    t = threading.Thread(target=spin, daemon=True)
    t.start()
    try:
        return fn()
    finally:
        stop.set()
        t.join()
        _out(f'\r\x1b[K\x1b[1F\x1b[J{SHOW}')
