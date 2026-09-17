{% if not installed %}
## SmartEVSE Session Logger

Turns the entities your SmartEVSE already publishes over MQTT into a
persistent, exportable log of charge sessions — MID-accurate kWh per
session, a nightly completeness check, and CSV export on demand or on a
schedule. No OCPP backend needed for ERE / mileage-reimbursement logging.
{% endif %}

## Features

- Session start/end detection from your SmartEVSE's own MQTT entities only —
  no car integration, no SOC, no brand assumptions.
- MID-accurate kWh per session.
- Self-healing after a Home Assistant or SmartEVSE restart.
- Optional nightly check against the SmartEVSE's own lifetime energy
  counter, with automatic correction of small rounding gaps and clear
  flagging of anything bigger.
- CSV export via service call, plus optional automatic weekly/monthly export
  with notification.
- 100% UI-configured — no YAML.

{% if not installed %}
See the [full README](https://github.com/Stroomregie/smartevse-session-logger#readme)
for requirements, configuration and how the completeness check works.
{% endif %}
