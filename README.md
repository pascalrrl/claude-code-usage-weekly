# claude-code-usage-weekly

Is the weekly Claude limit getting smaller? This tool measures how much Claude Code usage your
weekly limit allows, across all your computers, week after week.

It reads the transcripts Claude Code keeps on each computer and prices every request at the API
list prices: the **API-price equivalent**. The amount used from the start of a limit week up to the
message *"You've hit your weekly limit"* is the size of your weekly quota in dollars. If that
number drops over the weeks, the limit got smaller.

Everything runs locally with Python 3.9+ and the standard library; nothing is sent anywhere.

> Unofficial. Not affiliated with or endorsed by Anthropic.


## Quick start

```sh
git clone https://github.com/pascalrrl/claude-code-usage-weekly.git
cd claude-code-usage-weekly
python3 start.py
```

On Windows, use `python` instead of `python3`. The first start asks two questions in the terminal –
a name for this computer and your weekly reset – and writes `settings.json`. After that, `start.py`
shows a menu:

```
◆  What do you want to do?
│  ● Count this computer
│  ○ Build and open the report
│  ○ Settings
│  ○ Quit
```

Choose with the arrow keys and Enter. **Count** reads this computer's Claude Code transcripts of the
last 30 days into `data/<host name>/`. **Build** writes `report.html` from everything in `data/` and
opens it in your browser. **Settings** shows every setting with its value on one screen –
the names of the computers and the weekday, time and time zone of the weekly reset – and changes
the one you choose, without editing any file; the time zone is picked from a list that filters as
you type. Back (or Esc) leaves Settings. After each of them the screen is cleared and the menu comes back, with
the result on top, until you choose Quit.

It runs on macOS, Linux and Windows. In the classic Windows console it uses plain symbols; Windows
Terminal shows the full set. Without a terminal, or with `NO_COLOR` set, it asks plain numbered
questions instead.

`scan_usage.py` and `build_report.py` also run on their own, without questions – for scheduled runs,
or for more options (see [Every few weeks](#every-few-weeks)).


## Setup

### 1. Keep transcripts for 60 days

Claude Code deletes transcripts after 30 days by default (`cleanupPeriodDays`). Older weeks can
then no longer be counted. `start.py` shows the current value (in Settings when it is too short); to change it,
add this to `~/.claude/settings.json` on every computer (Windows: `C:\Users\<you>\.claude\settings.json`):

```json
{
  "cleanupPeriodDays": 60
}
```

If the file already has content, add only the line `"cleanupPeriodDays": 60,` inside the braces.
This is Claude Code's own settings file, not the `settings.json` of this tool.

### 2. Your settings: `settings.json`

`start.py` writes `settings.json` in this folder and changes it under Settings. It holds your own
settings and is not part of the repository (it is in `.gitignore`). You can also edit it:

```json
{
  "week_reset": { "weekday": "thursday", "time": "17:00", "timezone": "America/New_York" },
  "name": "Laptop",
  "computers": { "desktop-abc123": "Desktop" }
}
```

- **`week_reset`** – when your weekly limit resets; it differs per account. `start.py` reads it from
  the line `/usage` shows in Claude Code (*"Resets Mar 12, 5pm (America/New_York)"*), or asks for
  weekday, time and time zone. `timezone` is an IANA name like `America/New_York` or `Asia/Tokyo`;
  on Windows, any zone other than `UTC` needs `pip install tzdata`. Use the same reset on every
  computer. If it does not match the limit messages, the report warns you; week files counted with
  another reset are skipped. Set it before the first count: week files are named and cut by it.
- **`name`** – the name of this computer in the report. It is saved in every week file this computer
  writes, so the report shows it wherever the data is copied. Without it, the folder name (the
  host name) is shown.
- **`computers`** (optional) – names that override the name a computer's data carries, by data
  folder. Set them under Settings, where every computer whose data is in `data/` has a line.

Without `settings.json`, `build_report.py` stops and points to `start.py`; `scan_usage.py` also
takes the weekly reset as `--reset` (see the next section but one).

### 3. Check the prices

`prices.json` holds the API list prices per model, in dollars per million tokens. It is the same
for everyone and part of the repository:

```json
"claude-opus-5-5": [
  { "from": null, "until": null, "input": 4, "output": 20, "cache_write_5m": 5, "cache_write_1h": 8, "cache_read": 0.2 }
]
```

- A model name matches the longest entry it starts with: `claude-haiku-4-5-20251001` uses
  `claude-haiku-4-5`.
- Each model has a price history. `from` is the first day a price applies, `until` the first day it
  no longer applies (both `YYYY-MM-DD`, UTC; `null` means open-ended). When a price changes, set
  `until` on the old entry and add a new one:

  ```json
  "claude-opus-5-5": [
    { "from": null,         "until": "2027-03-01", "input": 4, "output": 20, "cache_write_5m": 5, "cache_write_1h": 8, "cache_read": 0.2 },
    { "from": "2027-03-01", "until": null,         "input": 3, "output": 15, "cache_write_5m": 3.75, "cache_write_1h": 6, "cache_read": 0.15 }
  ]
  ```

  Overlapping periods are an error.
- The week files hold token counts, not dollars. The report applies the prices valid in each hour,
  so after fixing or adding a price you only build the report again – old weeks are priced
  correctly too, even if their transcripts are gone.
- A model without a price counts as $0, and the report warns about it.

### 4. More than one computer (optional)

Count every computer you use Claude Code on, and build the report on one of them. There are two
ways to count another computer:

- **Clone this repository there** and run `python3 start.py`: set the same weekly reset and a name,
  then choose *Count this computer*.
- **Copy only `scan_usage.py` there** – it runs on its own, without the other files – and pass the
  weekly reset and a name:

  ```sh
  python3 scan_usage.py --reset "thursday 17:00 America/New_York" --name "Desktop"
  ```

  `--reset` also takes the line `/usage` shows (*"Resets Mar 12, 5pm (America/New_York)"*).

Each computer writes its own folder `data/<host name>/`. To build one report for all of them, copy
each computer's own folder into `data/` on the computer that builds the report, replacing existing
files, then build there. Copy only a computer's own folder, never a whole `data/` folder: older
files of other computers could overwrite newer ones.

The report shows every computer by the name its data carries. To call one differently, rename it on
the building computer under Settings. Folders with the same name are
added up. `--pc <folder>` sets the folder name instead of the host name.


## Every few weeks

Count every computer **at least every 4 weeks** (with 60 days of retention; every 2 weeks with the
default 30), otherwise transcripts are gone before they are counted. Use `start.py`, or run the two
steps directly – they ask nothing, which suits scheduled runs, and take more options:

```sh
python3 scan_usage.py                  # weeks of the last 30 days
python3 scan_usage.py -t0 2026-10-01   # from that day up to today
python3 build_report.py
```

| Option | Meaning |
|---|---|
| `-t0 YYYY-MM-DD` | first day (default: today − 30 days) |
| `-t1 YYYY-MM-DD` | last day, included (default: today) |
| `--reset "thursday 17:00 America/New_York"` | weekly reset (default: `week_reset` in `settings.json`) |
| `--name NAME` | name of this computer in the report (default: `name` in `settings.json`, else the folder) |
| `--pc FOLDER` | data folder of this computer (default: host name) |
| `--projects PATH` | Claude Code transcripts (default: `~/.claude/projects`) |
| `--force` | replace week files even if the new count finds less |

Every week touching the range is counted in full. Counting a finished week again replaces its file
only if the new count finds at least as many requests and no less history; otherwise transcripts
were deleted meanwhile and the existing file is kept.


## Reading the report

**At the top:** the mean weekly quota, the last measurement against the weeks before, the largest
week without a limit hit, and the mean usage per week.

**Quota per week** – the main chart:
- **Dot:** the weekly limit was hit; the value is the API-price equivalent of all computers up to
  that moment. This is the size of the quota.
- **Triangle:** a full week without a limit hit; the quota was at least this big (`≥`).
- **Grey band:** spread of the weeks before the last measurement (at least ±5 %).

**Spotting a change:**
- If the newest dot lies **outside the grey band**, the report colors it **amber**. That is a first
  hint, not proof.
- If the **following weeks** stay at the new level, the limit changed.
- A triangle clearly above the dots means the limit was larger in that week, or something outside
  Claude Code counted in the weeks with a limit hit. The report shows it in amber.
- A single low week can have a simple cause: claude.ai and the Claude apps count towards the same
  limit, but not into this measurement.

**Usage per week** shows the API-price equivalent per week, stacked by computer. **Model mix** shows
each model's share; a shift in the mix can change the dollar value of the quota without any change
by Anthropic, since it is unknown how the limit weighs the models. **Index** compares the dollar
value with the plain token count. The **table** lists all numbers per week, the limit hits and the
notes.

**Faded** bars and rows are weeks that are not fully counted: the current week, weeks whose first
days are no longer in the transcripts, or weeks a computer did not count. They are left out of the
mean, the band and the trend.


## Messages

| Message | Meaning | What to do |
|---|---|---|
| `kept the existing file` | A finished week was counted before; its transcripts are partly deleted now. | Nothing. |
| `current week` | The week is not over yet. | Nothing; the next scan completes it. |
| `transcripts only from …` | The first days of the week are no longer in the transcripts. | Check `cleanupPeriodDays`. Harmless on a new computer, see below. |
| `No price in prices.json` (report) | A model without a price; it counts as $0. | Add it to `prices.json`, build the report again. |
| `settings.json not found` | No settings yet. | Run `start.py`; or pass `--reset` to `scan_usage.py`. |
| `has an older format and is skipped` (report) | A week file of an incompatible version. | Count the week again, if its transcripts still exist. |
| `was counted with another weekly reset` (report) | A week file was cut with a different reset than `week_reset` in `settings.json`, e.g. a wrong `--reset` on another computer. | Count it again there with the same reset. |
| `<computer>: not counted` (report) | A computer has no file for this week. | Scan on that computer and copy its folder. |
| `Reset per limit message …` (report) | The limit messages name another reset time. | Correct the reset in `start.py` → Settings, then count the weeks again. |


## How it works

- `scan_usage.py` reads `~/.claude/projects/**/*.jsonl`, counts every request once (by message
  and request id), and sums its input, output, cache-write (5 min and 1 h) and cache-read tokens
  per model and per hour of the limit week. It also keeps the limit messages (*"You've hit your
  weekly limit"*, session limits) with their time and text.
- Each week file `data/<computer>/<start date>.json` holds these counts, the time of the scan and
  the oldest transcript entry found.
- `build_report.py` merges all computers, prices the tokens with `prices.json` and writes
  `report.html`. Because every file has hourly values, it can add up all computers up to the moment
  the limit was hit, even when the limit was hit on another computer. The hour of the limit hit
  counts in full.
- A **new computer** has no old transcripts. If its oldest entry is more than 7 days younger than
  the 30 days after which Claude Code deletes at the earliest, the report treats it as new: the
  weeks before its first transcript count as full, with $0 for it. This only holds as long as no
  computer has `cleanupPeriodDays` below 30.


## Limits

- Only Claude Code is measured. Usage on claude.ai and in the Claude apps counts towards the same
  limit but is not visible here.
- The API-price equivalent is an approximation. How the subscription limit weighs models and token
  types is not public.
- The limit is only measured in weeks in which it was hit; other weeks give a lower bound.


## Privacy

All data stays on your computers. `settings.json`, `data/` and `report.html` are listed in
`.gitignore` – do not commit them: the week files show when and how much you worked, the folder
names and `computers` are your host names, and `week_reset` is your account's reset time. The report loads the chart library ECharts from the jsDelivr CDN when
you open it.


## Files

| File | Purpose |
|---|---|
| `start.py` | start here: menu to count, build and change the settings; writes `settings.json` (not in the repository) |
| `prompts.py` | the small terminal UI of `start.py` (arrow keys, colors; plain questions without a terminal or with `NO_COLOR`) |
| `scan_usage.py` | counts this computer's usage, one file per limit week; runs on its own and defines the limit weeks for the other two scripts |
| `build_report.py` | prices the week files and writes `report.html` |
| `prices.json` | API list prices per model, with their history |
| `template.html`, `theme.json` | layout and colors of the report |


## License

[MIT](LICENSE)
