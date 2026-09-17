# SmartEVSE Session Logger

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Home Assistant custom integration that turns the entities your **[SmartEVSE](https://github.com/SmartEVSE/SmartEVSE-3)**
already publishes over MQTT into a persistent, exportable log of charge
sessions — start time, end time, kWh from your MID-certified meter, how the
session ended, and a nightly check that the log is actually complete.

It was built to answer one very specific, very common need in the SmartEVSE
community: **"I need an accurate charging log for my ERE / tax mileage
reimbursement, and I don't want to run a full OCPP backend just for that."**
If your SmartEVSE has a Modbus-coupled MID meter (as most installations do),
this integration is all you need.

## Why not just use OCPP?

OCPP is built for public charge points with billing, remote start/stop and
multi-vendor backends — a lot of infrastructure for what is, for most home
and small-fleet users, a much simpler problem: *"tell me, per session, how
much energy went into the car, and let me export that."* SmartEVSE already
knows this from its own state machine and its MID meter; this integration
just listens, records it reliably, and makes it exportable.

## What it does

- **Session detection** — purely from the entities your SmartEVSE publishes
  over MQTT (state + EV plug state). No car integration, no SOC, no brand
  assumptions: it works identically for every car, because it never looks at
  the car at all.
- **MID-accurate energy per session** — reads the start and end value of your
  configured cumulative-energy (MID) sensor for every session.
- **Self-healing** — if Home Assistant or the SmartEVSE restarts mid-session,
  the integration notices on startup and again every hour (configurable) and
  recovers the session instead of silently losing it.
- **Nightly completeness check (optional)** — compares the sum of your logged
  sessions against the SmartEVSE's own lifetime energy counter and either
  confirms everything matches, auto-corrects a small single-session rounding
  gap, or flags a larger/ambiguous gap for you to check by hand. See
  [How the completeness check works](#how-the-completeness-check-works).
- **CSV export, on demand or on a schedule** — a service call
  (`smartevse_session_logger.export_csv`) you can trigger from a dashboard
  button or the Developer Tools, plus an optional weekly/monthly automatic
  export that emails (or push-notifies, or whatever your chosen
  `notify.*` service supports) a summary and a link to the CSV.
- **Fully configured through the UI** — no YAML editing. Set it up once by
  pointing it at your entities; adjust notifications, schedules and optional
  entities any time via the gear icon.

## What it deliberately does *not* do

- **No SOC / battery percentage, no car brand or model.** Almost nobody has a
  reliable, brand-agnostic way to read state-of-charge from an arbitrary EV,
  so this integration never tries. Everything it logs comes from the
  SmartEVSE itself.
- **No OCPP, no billing, no RFID/user identification.** If you need those,
  this isn't a replacement — it solves the "I just need a trustworthy log"
  case.
- **No cloud dependency.** All data stays in your Home Assistant's local
  storage (`.storage/`) and, for exports, `www/`.

## Requirements

- A **SmartEVSE** (SmartEVSE-3 or newer firmware) with **MQTT enabled**, so
  it publishes its state via Home Assistant's MQTT discovery. This is the
  standard way of connecting a SmartEVSE to Home Assistant — see the
  [SmartEVSE-3 documentation](https://github.com/SmartEVSE/SmartEVSE-3) if
  you haven't set this up yet.
- A Modbus-coupled **MID meter** on the SmartEVSE, so it exposes a cumulative
  imported-energy sensor (commonly named `..._evimportactiveenergy`).
- Home Assistant 2024.12 or newer.
- (Optional, for the nightly completeness check) the SmartEVSE's own lifetime
  "total energy charged" sensor (commonly `..._evtotalenergycharged`).
- (Optional, for notifications/exports by email or push) an existing
  `notify.*` service already configured in Home Assistant, e.g.
  `notify.smtp` for email or a mobile app's `notify.mobile_app_*`.

## Installation

### Via HACS (recommended)

This integration isn't in the default HACS store yet. Until then, add it as
a custom repository:

1. HACS → the three-dot menu (top right) → **Custom repositories**.
2. Repository: `https://github.com/Stroomregie/smartevse-session-logger`,
   category: **Integration**.
3. Find **SmartEVSE Session Logger** in HACS and install it.
4. Restart Home Assistant.

### Manual

1. Copy `custom_components/smartevse_session_logger` into your Home
   Assistant `config/custom_components/` folder.
2. Restart Home Assistant.

## Configuration

Settings → Devices & Services → **Add Integration** → search for
**SmartEVSE Session Logger**.

### Step 1 — required entities

| Field | What to pick |
|---|---|
| Name | A name for this SmartEVSE (used as the device/entity prefix). |
| State sensor | e.g. `sensor.smartevse_xxxx_state` — reports `Charging` while charging. |
| EV plug state sensor | e.g. `sensor.smartevse_xxxx_evplugstate` — `Connected` / `Disconnected`. |
| Energy sensor | e.g. `sensor.smartevse_xxxx_evimportactiveenergy` — cumulative kWh from the MID meter. This is the number that drives every session's energy calculation. |

That's enough to start logging sessions. Everything below is optional and
can be changed later via the integration's **Configure** (gear icon).

### Step 2 — extra entities (optional, via Configure → "Extra entities")

| Field | Effect |
|---|---|
| Total energy charged sensor | e.g. `..._evtotalenergycharged`. Adding this **enables the nightly completeness check**. Without it, the check is silently skipped. |
| Charge current sensor | Logged as context on each session (e.g. `..._chargecurrent`). |
| Mode entity | e.g. `select.smartevse_xxxx_mode`. Logged as context on each session (Solar/Normal/Smart/Off at session start). |

### Step 3 — notifications (via Configure → "Notifications")

| Field | Effect |
|---|---|
| Send notifications | Turns on/off using a `notify.*` service for completeness-check results and periodic exports. |
| Notify service | e.g. `notify.email_me`, `notify.mobile_app_phone`. Any HA notify service that accepts `title`/`message` works. |

Completeness-check issues (corrections or unresolved gaps) always also
create a Home Assistant **persistent notification**, regardless of this
setting — so you won't miss a real issue just because SMTP is down.

### Step 4 — checks & periodic export (via Configure → "Checks & periodic export")

| Field | Default | Effect |
|---|---|---|
| Hourly watchdog | on | Extra safety net: if the SmartEVSE reports `Charging` but no session is active (a missed MQTT event), a session is recovered and you're notified. |
| Nightly completeness check | on | Requires the total-energy sensor (Step 2). See below for the algorithm. |
| Check time | 04:30 | When the nightly check runs. |
| Allowed deviation | 0.02 kWh | Below this, a gap is considered rounding noise and ignored. |
| Automatically export & notify | off | Turn on to get a periodic CSV export + notification. |
| Frequency | weekly | Weekly (always the last full 7 days) or monthly (always the previous calendar month). |
| Day / time | Monday, 06:00 | When the export is generated and sent. |

## Entities

Assuming the default name "SmartEVSE" (your slug will differ if you renamed
it):

| Entity | Description |
|---|---|
| `sensor.smartevse_session_state` | `idle` / `connected_idle` / `active`. Attributes include the in-progress session's id, start time and start kWh. |
| `binary_sensor.smartevse_charging` | On while a session is actively being logged. |
| `sensor.smartevse_last_session_energy` | kWh of the most recently *completed* session, with full session details as attributes (start, end, end reason, reconciliation status, ...). |
| `sensor.smartevse_reconciliation` | `unknown` / `ok` / `corrected` / `unresolved` — result of the last nightly completeness check, with the full report text as an attribute. |

## Services

### `smartevse_session_logger.export_csv`

Writes a semicolon-separated CSV (importable directly in Excel/NL locale) of
sessions for a period to `config/www/smartevse_session_logger/` and returns
the path, a URL, the row count and total kWh.

```yaml
action: smartevse_session_logger.export_csv
data:
  period: last_month   # or: last_7_days, last_30_days, this_month, this_year, last_year
```

Or a custom range:

```yaml
action: smartevse_session_logger.export_csv
data:
  start_date: "2026-01-01"
  end_date: "2026-03-31"
```

### `smartevse_session_logger.force_reconciliation`

Runs the nightly completeness check immediately. Useful right after changing
the tolerance, or to verify your setup during initial configuration.

See [`dashboard/example_dashboard.yaml`](dashboard/example_dashboard.yaml)
for a ready-to-paste Lovelace view with a status card, last-session details,
a charging history graph and an export button.

## How session detection works

A small state machine, driven only by the two required entities:

- **`idle → connected_idle`**: EV plug sensor goes to `Connected`.
- **`connected_idle → active`**: state sensor goes to `Charging`. A new
  session starts: id, start time and start kWh (from the energy sensor) are
  recorded immediately.
- **`active → connected_idle`**: state sensor leaves `Charging` while the
  plug is still `Connected` (e.g. charge limit reached, manually stopped,
  scheduled pause). The session ends with reason `charging_stopped`.
- **`active/connected_idle → idle`**: EV plug sensor goes to `Disconnected`.
  If a session was active, it ends with reason `disconnected`.

Every session is written to storage the moment it *starts*, not only when it
ends — so an in-progress session survives a Home Assistant restart, and the
nightly check and CSV export always see it.

## How the completeness check works

This only runs if you've configured a **total energy charged** sensor (the
SmartEVSE's own lifetime counter, independent of this integration's
session log).

1. The very first time it runs, it has no prior reference point, so it just
   records the current counter value as a baseline and accepts all sessions
   so far — no corrections are ever guessed on data recorded before this
   check was enabled.
2. On every later run, it adds up the energy of all sessions logged since the
   last check and compares that to how much the SmartEVSE's own counter
   actually increased over the same period.
   - **Within tolerance** (default 0.02 kWh) → nothing to do.
   - **A gap, and exactly one session since the last check** → the gap is
     almost certainly rounding/measurement noise for that one session, so
     it's added to that session's logged energy automatically. The original
     (uncorrected) value is kept as `energy_kwh_raw` for transparency.
   - **A gap, and more than one session since the last check** → it's not
     safe to guess which session is responsible, so nothing is
     auto-corrected. All of those sessions are flagged
     `reconciliation_unresolved` and you get a notification to check them
     by hand (e.g. a session your Home Assistant restarted during, before
     the watchdog had a chance to recover it).

The full reasoning for the last run is always available as the
`report_text` attribute on `sensor.smartevse_reconciliation`.

## Multiple SmartEVSEs

Add the integration again for a second SmartEVSE — each config entry is
fully independent (own storage, own entities, own schedule). Services that
can target a specific one accept an optional `config_entry_id`; if you only
have one, it's picked automatically.

## Where your data is stored

Nothing is written loose into your `config/` root:

- Session history (the actual log) lives in Home Assistant's own
  `.storage/smartevse_session_logger_<entry_id>` — the standard place every
  HA integration keeps its state, namespaced by filename so it never mixes
  with anything else.
- CSV exports are written to `config/www/smartevse_session_logger/`, so they
  live in their own subfolder under `www/`, not scattered through it.

Nothing is sent anywhere except through the `notify.*` service *you*
configure.

## Running alongside an existing DIY session logger

If you already have your own automations logging SmartEVSE sessions (for
example tied to a car-specific integration for state-of-charge), you can
install this integration **side by side** without any risk to your existing
setup. It only *reads* the SmartEVSE entities you point it at — it never
writes to them — and it uses its own domain (`smartevse_session_logger`),
its own `.storage/` file and its own entities. It does not know about, and
cannot touch, any pre-existing helpers, automations, or log files your own
setup already has.

That makes it safe to run both in parallel for a while — e.g. to compare
your existing log against this one before deciding whether to keep both (one
for detailed per-brand data, one as the authoritative export source) or
retire the old one. As with any new custom integration, taking a Home
Assistant backup first is still good practice — not because this
integration touches your existing data, but so you always have a clean
rollback point.

One thing to expect: session *boundaries* may differ slightly between the
two loggers if your existing setup ends a session based on car-reported
signals (e.g. "charging complete" from the car) rather than the SmartEVSE's
own state. This integration only ends a session when the SmartEVSE itself
reports it stopped charging or the cable was disconnected — which is
arguably more accurate for MID/ERE purposes, since it reflects actual
current flow rather than the car's own reporting.

## Extending with car-specific data (e.g. Tesla BLE state-of-charge)

This integration deliberately never looks at the car — no SOC, no brand —
because there's no reliable, brand-agnostic way to do that, and getting it
wrong would undermine trust in the log. But if *you* have a car integration
that exposes SOC, you can layer that on top yourself with a plain
automation in your own config, using the events this integration fires on
the Home Assistant bus:

- `smartevse_session_logger_session_started`
- `smartevse_session_logger_session_ended`

Both carry the full session record as event data (`session_id`, `start`/
`end`, `energy_start_kwh`/`energy_end_kwh`/`energy_kwh`, `end_reason`, ...).
For example, to log the Tesla's SOC alongside each session without ever
touching this integration's code:

```yaml
automation:
  - alias: "Log Tesla SOC at SmartEVSE session start"
    triggers:
      - trigger: event
        event_type: smartevse_session_logger_session_started
    actions:
      - action: logbook.log
        data:
          name: "EV sessie {{ trigger.event.data.session_id }}"
          message: >
            Start SOC: {{ states('sensor.tesla_ble_charge_level') }}%
            (limiet {{ states('sensor.tesla_ble_charge_limit') }}%)
```

This keeps the community package universal while letting your own setup
stay as detailed as you like.

## Contributing

Issues and PRs are welcome at
[github.com/Stroomregie/smartevse-session-logger](https://github.com/Stroomregie/smartevse-session-logger).
If your SmartEVSE publishes entity states with different text than described
above (e.g. a non-English firmware build), please open an issue with your
exact entity states — this integration currently expects the stock English
state strings (`Charging`, `Connected`, `Disconnected`).

## License

[MIT](LICENSE) — use it, fork it, ship it as part of your own dashboard.
