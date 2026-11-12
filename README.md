# Claude Code Usage Weekly

Is your weekly Claude limit getting smaller? This tool measures how much Claude Code usage your
weekly limit allows – in dollars at API list prices, across all your computers, week after week.

Claude Code keeps a transcript of every session on your computer. The tool reads them and prices
every request at the API list prices: the **API-price equivalent**. What you used from the start of
a limit week up to the message *"You've hit your weekly limit"* is the size of your weekly quota.
If that number drops over the weeks, the limit got smaller.

It runs locally on macOS, Linux and Windows, with Python 3.9 or newer and nothing else. No data is
sent anywhere.


## Quick start

```sh
git clone https://github.com/pascalrrl/claude-code-usage-weekly.git
cd claude-code-usage-weekly
python3 start.py          # Windows: python start.py
```

The first start asks for a name for this computer and when your weekly limit resets. For the
reset, paste the line `/usage` shows in Claude Code (*"Resets Mar 12, 5pm (America/New_York)"*), or
pick weekday, time and time zone. Then a menu appears:

```
◆  What do you want to do?
│  ● Count this computer
│  ○ Build and open the report
│  ○ Settings
│  ○ Quit
```

- **Count this computer** reads the transcripts of the last 30 days.
- **Build and open the report** writes `report.html` and opens it in your browser.
- **Settings** changes the names and the weekly reset.

Use the arrow keys and Enter; Back or Esc goes back.


## Keep transcripts for 60 days

Claude Code deletes transcripts after 30 days by default, and a week that is gone can no longer be
counted. Set it to 60 days in Claude Code's own settings file, `~/.claude/settings.json`
(Windows: `C:\Users\<you>\.claude\settings.json`), on every computer:

```json
{
  "cleanupPeriodDays": 60
}
```

If the file already has content, add only `"cleanupPeriodDays": 60,` as the first line after its
opening brace.

Then count each computer **at least every 4 weeks** – every 2 weeks if you keep the default.
`start.py` reminds you as long as the value is below 60.


## Several computers

Count every computer you use Claude Code on, and build the report on one of them:

1. **Count** each computer: clone the repository there, run `python3 start.py`, enter a name and
   the **same** weekly reset, and choose *Count this computer*.
2. **Copy** each computer's folder from `data/` into `data/` on the computer that builds the report,
   replacing existing files. Copy only a computer's own folder, never a whole `data/` folder: older
   files of other computers could overwrite newer ones.
3. **Build** the report there.

Instead of cloning, you can copy only `scan_usage.py` to a computer – it runs on its own:

```sh
python3 scan_usage.py --reset "thursday 17:00 America/New_York" --name "Desktop"
```


## Reading the report

**At the top:** the mean weekly quota, the last measurement against the weeks before, the largest
week without a limit hit, and the mean usage per week.

**Quota per week** – the main chart:
- **Dot:** the weekly limit was hit; the value is the API-price equivalent of all computers up to
  that moment. This is the size of the quota.
- **Triangle:** a full week without a limit hit; the quota was at least this big (`≥`).
- **Grey band:** spread of the weeks before the last measurement (at least ±5 %).

**Spotting a change:**
- If the newest dot lies **outside the grey band**, it turns **amber**. That is a first hint, not
  proof; if the **following weeks** stay at the new level, the limit changed.
- A triangle clearly above the dots means the limit was larger in that week, or something outside
  Claude Code counted in the weeks with a limit hit. It turns amber too.
- A single low week can have a simple cause: claude.ai and the Claude apps count towards the same
  limit, but not into this measurement.

**Further charts:** usage per week, stacked by computer; the model mix (a shift in it can change the
dollar value of the quota, since it is unknown how the limit weighs the models); and an index that
compares the dollar value with the plain token count. The **table** lists all numbers per week, the
limit hits and the notes.

**Faded** bars and rows are weeks that are not fully counted: the current week, weeks whose first
days are no longer in the transcripts, or weeks a computer did not count. They are left out of the
mean, the band and the trend.


## Reference

### `settings.json`

`start.py` writes it and changes it under Settings; you can also edit it. It is your own file, not
part of the repository.

```json
{
  "week_reset": { "weekday": "thursday", "time": "17:00", "timezone": "America/New_York" },
  "name": "Laptop",
  "folder": "laptop-7f3e",
  "computers": { "desktop-9a1c": "Desktop" }
}
```

- **`week_reset`** – when your weekly limit resets; it differs per account. Use the same on every
  computer, and set it before the first count: the weeks are cut by it. `timezone` is a name like
  `America/New_York`; on Windows, zones other than `UTC` need `pip install tzdata`.
- **`name`** – this computer's name in the report. It is saved in its data, so every computer that
  builds the report shows it.
- **`folder`** – this computer's folder in `data/`. It is set once at the first start, to the host
  name and four random characters, and never changes: a renamed host, or two computers with the
  same host name, cannot mix their data. Renaming the computer changes only `name`.
- **`computers`** (optional) – other names for computers whose data was copied here, by folder.

### `prices.json`

The API list prices per model, in dollars per million tokens. It is part of the repository:

```json
"claude-opus-5-5": [
  { "from": null, "until": null, "input": 4, "output": 20, "cache_write_5m": 5, "cache_write_1h": 8, "cache_read": 0.2 }
]
```

- A model matches the entry of the same name, also with a date appended: `claude-haiku-4-5-20251001`
  uses `claude-haiku-4-5`. A new model never takes an older one's price: `claude-fable-5-3` does not
  use `claude-fable-5` but is reported as without a price.
- Claude Haiku 5.5 costs more for a prompt over 100,000 tokens (all input tokens, cache included).
  Such requests are counted as `claude-haiku-5-5+long`, priced by their own entry.
- When a price changes, end the old entry with `until` and add a new one with `from` (both
  `YYYY-MM-DD`, UTC; `null` means open-ended):

  ```json
  "claude-opus-5-5": [
    { "from": null,         "until": "2027-03-01", "input": 4, "output": 20, "cache_write_5m": 5, "cache_write_1h": 8, "cache_read": 0.2 },
    { "from": "2027-03-01", "until": null,         "input": 3, "output": 15, "cache_write_5m": 3.75, "cache_write_1h": 6, "cache_read": 0.15 }
  ]
  ```

- The data holds token counts, not dollars: after fixing or adding a price, just build the report
  again – old weeks are priced correctly too.
- A model without a price counts as $0, and the report warns about it.

### Command line

`scan_usage.py` and `build_report.py` also run on their own, without questions – e.g. for
scheduled runs:

```sh
python3 scan_usage.py                  # weeks of the last 30 days
python3 scan_usage.py -t0 2026-10-01   # from that day up to today
python3 build_report.py
```

| Option of `scan_usage.py` | Meaning |
|---|---|
| `-t0 YYYY-MM-DD` | first day (default: today − 30 days) |
| `-t1 YYYY-MM-DD` | last day, included (default: today) |
| `--reset "thursday 17:00 America/New_York"` | weekly reset (default: `week_reset` in `settings.json`); also takes the line `/usage` shows |
| `--name NAME` | name of this computer in the report (default: `name` in `settings.json`) |
| `--pc FOLDER` | data folder (default: `folder` in `settings.json`, else the host name) |
| `--projects PATH` | Claude Code transcripts (default: `~/.claude/projects`) |
| `--force` | replace week files even if the new count finds less |

Every week touching the range is counted in full. A finished week that is counted again keeps its
old file if the new count finds less – its transcripts were partly deleted in the meantime.

### Messages

| Message | Meaning | What to do |
|---|---|---|
| `kept the existing file` | A finished week was counted before; its transcripts are partly deleted now. | Nothing. |
| `current week` | The week is not over yet. | Nothing; the next count completes it. |
| `transcripts only from …` | The first days of the week are no longer in the transcripts. | Check `cleanupPeriodDays`. Harmless on a new computer. |
| `<computer>: not counted` | A computer has no data for this week. | Count on that computer and copy its folder. |
| `No price in prices.json` | A model without a price; it counts as $0. | Add it to `prices.json`, build again. |
| `Reset per limit message …` | The limit messages name another reset time. | Correct the reset under Settings, then count the weeks again. |
| `was counted with another weekly reset` | A week file was cut with another reset, e.g. a wrong `--reset` on another computer. | Count it again there with the same reset. |
| `both count the same week of …` | Two folders with the same computer name hold the same week; only the one with more requests counts. | Delete the other file, or give the computers different names if they are two. |
| `cannot be read` / `is damaged` / `older format` | A week file the report cannot use; it is skipped. | Count that week again, if its transcripts still exist. |
| `settings.json not found` | No settings yet. | Run `start.py`, or pass `--reset` to `scan_usage.py`. |


## How it works

- `scan_usage.py` reads `~/.claude/projects/**/*.jsonl` and counts every response once (by message
  and request id). It sums input, output, cache-write (5 min and 1 h) and cache-read tokens per
  model and per hour of the limit week, and keeps the limit messages with their time and text.
  Requests in fast mode (`/fast`) are left out: they are paid from usage credits and do not count
  towards the plan's limits.
- Each week goes into `data/<folder>/<start date>.json`, with the time of the count and the oldest
  transcript entry found.
- `build_report.py` merges all computers, prices the tokens with `prices.json` and writes
  `report.html`. Thanks to the hourly values it can add up all computers up to the moment the limit
  was hit, even if that happened on another computer.
- A **new computer** has no old transcripts. If its oldest entry is clearly younger than the 30 days
  Claude Code keeps at least, the weeks before it count as full, with $0 for that computer.


## Limits

- Only Claude Code is measured. Usage on claude.ai and in the Claude apps counts towards the same
  limit but is not visible here.
- The API-price equivalent is an approximation. How the subscription limit weighs models and token
  types is not public.
- The limit is only measured in weeks in which it was hit; other weeks give a lower bound.


## Privacy

All data stays on your computers. `settings.json`, `data/` and `report.html` are in `.gitignore` –
do not commit them: the data shows when and how much you worked, and the folder names contain your
host names. The report loads the chart library ECharts from the jsDelivr CDN, checked against a
fixed hash; offline the charts stay empty and the table still works.


## Files

| File | Purpose |
|---|---|
| `start.py` | start here: the menu to count, build and change the settings |
| `prompts.py` | the terminal interface of `start.py` |
| `scan_usage.py` | counts this computer's usage, one file per limit week; runs on its own |
| `build_report.py` | prices the week files and writes `report.html` |
| `prices.json` | API list prices per model, with their history |
| `template.html`, `theme.json` | layout and colors of the report |


## License

[MIT](LICENSE) · Developed with AI assistance.
