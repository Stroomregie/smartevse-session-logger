# Changelog

## 0.1.0 — Initial release

- Session detection driven purely by SmartEVSE MQTT entities (state + EV
  plug state), no car/SOC dependency.
- MID-accurate energy per session.
- Startup + hourly watchdog self-healing.
- Optional nightly completeness check against the SmartEVSE's own lifetime
  energy counter, with automatic correction of small single-session gaps.
- `export_csv` and `force_reconciliation` services.
- Optional automatic weekly/monthly CSV export with notification.
- Fully UI-configured (config flow + options flow), English and Dutch
  translations.
- Example Lovelace dashboard.
