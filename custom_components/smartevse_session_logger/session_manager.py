"""Core session state machine, storage, reconciliation and export logic."""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util, slugify

from .const import (
    CONF_CURRENT_SENSOR,
    CONF_ENERGY_SENSOR,
    CONF_MODE_ENTITY,
    CONF_NAME,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_SERVICE,
    CONF_PLUG_SENSOR,
    CONF_RECONCILE_TOLERANCE,
    CONF_STATE_SENSOR,
    CONF_TOTAL_ENERGY_SENSOR,
    DOMAIN,
    END_REASON_CHARGING_STOPPED,
    END_REASON_DISCONNECTED,
    END_REASON_WATCHDOG_RECOVERY,
    EVSE_STATE_CHARGING,
    EXPORT_DIR,
    PLUG_STATE_CONNECTED,
    PLUG_STATE_DISCONNECTED,
    SESSION_ACTIVE,
    SESSION_CONNECTED_IDLE,
    SESSION_IDLE,
    STORAGE_VERSION,
    UNAVAILABLE_STATES,
)

_LOGGER = logging.getLogger(__name__)

SIGNAL_UPDATE = f"{DOMAIN}_update"


def _float_state(hass: HomeAssistant, entity_id: str | None) -> float | None:
    """Read an entity's state as a float, or None if unavailable/unset."""
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in UNAVAILABLE_STATES:
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


def _raw_state(hass: HomeAssistant, entity_id: str | None) -> str | None:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in UNAVAILABLE_STATES:
        return None
    return state.state


class SessionManager:
    """Tracks charge sessions for a single configured SmartEVSE and persists them."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.slug = slugify(entry.data.get(CONF_NAME) or "smartevse")
        self.store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")
        self._data: dict[str, Any] = {"sessions": [], "reconciliation": {}}
        self._unsub_listeners: list[Any] = []

    # ------------------------------------------------------------------ #
    # Config / option accessors (options override data, so options-flow
    # changes take effect without recreating the entry)
    # ------------------------------------------------------------------ #
    def _opt(self, key: str, default: Any = None) -> Any:
        return self.entry.options.get(key, self.entry.data.get(key, default))

    @property
    def state_sensor(self) -> str:
        return self.entry.data[CONF_STATE_SENSOR]

    @property
    def plug_sensor(self) -> str:
        return self.entry.data[CONF_PLUG_SENSOR]

    @property
    def energy_sensor(self) -> str:
        return self.entry.data[CONF_ENERGY_SENSOR]

    @property
    def total_energy_sensor(self) -> str | None:
        return self._opt(CONF_TOTAL_ENERGY_SENSOR)

    @property
    def current_sensor(self) -> str | None:
        return self._opt(CONF_CURRENT_SENSOR)

    @property
    def mode_entity(self) -> str | None:
        return self._opt(CONF_MODE_ENTITY)

    @property
    def notify_service(self) -> str | None:
        if not self._opt(CONF_NOTIFY_ENABLED, False):
            return None
        return self._opt(CONF_NOTIFY_SERVICE)

    @property
    def watchdog_enabled(self) -> bool:
        return bool(self._opt("watchdog_enabled", True))

    @property
    def reconcile_enabled(self) -> bool:
        return bool(self._opt("reconcile_enabled", True))

    @property
    def reconcile_time(self) -> str:
        return self._opt("reconcile_time", "04:30:00")

    @property
    def export_enabled(self) -> bool:
        return bool(self._opt("export_enabled", False))

    @property
    def export_frequency(self) -> str:
        return self._opt("export_frequency", "weekly")

    @property
    def export_weekday(self) -> int:
        return int(self._opt("export_weekday", 0))

    @property
    def export_day_of_month(self) -> int:
        return int(self._opt("export_day_of_month", 1))

    @property
    def export_time(self) -> str:
        return self._opt("export_time", "06:00:00")

    @property
    def sessions(self) -> list[dict[str, Any]]:
        return self._data["sessions"]

    @property
    def reconciliation(self) -> dict[str, Any]:
        return self._data.setdefault("reconciliation", {})

    @property
    def session_state(self) -> str:
        """Derive the current session state from the last stored session + live sensors."""
        sessions = self._data.get("sessions") or []
        if sessions and sessions[-1].get("end") is None:
            return SESSION_ACTIVE
        if _raw_state(self.hass, self.plug_sensor) == PLUG_STATE_CONNECTED:
            return SESSION_CONNECTED_IDLE
        return SESSION_IDLE

    @property
    def current_session(self) -> dict[str, Any] | None:
        sessions = self._data.get("sessions") or []
        if sessions and sessions[-1].get("end") is None:
            return sessions[-1]
        return None

    @property
    def last_completed_session(self) -> dict[str, Any] | None:
        for session in reversed(self._data.get("sessions") or []):
            if session.get("end") is not None:
                return session
        return None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def async_load(self) -> None:
        stored = await self.store.async_load()
        if stored:
            self._data = stored
        self._data.setdefault("sessions", [])
        self._data.setdefault("reconciliation", {})

    async def _async_save(self) -> None:
        await self.store.async_save(self._data)
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    @callback
    def async_setup_listeners(self) -> None:
        self._unsub_listeners.append(
            async_track_state_change_event(
                self.hass, [self.state_sensor], self._async_handle_state_sensor
            )
        )
        self._unsub_listeners.append(
            async_track_state_change_event(
                self.hass, [self.plug_sensor], self._async_handle_plug_sensor
            )
        )

    @callback
    def async_unload_listeners(self) -> None:
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()

    async def async_reconcile_on_startup(self) -> None:
        """Self-heal if HA (re)started while a charge was already in progress."""
        if self.current_session is not None:
            return
        if _raw_state(self.hass, self.state_sensor) == EVSE_STATE_CHARGING:
            _LOGGER.warning(
                "%s is charging but no active session was recorded (HA/EVSE restart?) — "
                "recovering a session now",
                self.state_sensor,
            )
            await self._async_start_session(recovered=True)

    # ------------------------------------------------------------------ #
    # State machine
    # ------------------------------------------------------------------ #
    async def _async_handle_state_sensor(self, event: Event) -> None:
        new_state = event.data["new_state"]
        old_state = event.data["old_state"]
        if new_state is None:
            return
        new_val = new_state.state
        old_val = old_state.state if old_state else None

        if new_val == EVSE_STATE_CHARGING and self.current_session is None:
            await self._async_start_session()
        elif (
            old_val == EVSE_STATE_CHARGING
            and new_val != EVSE_STATE_CHARGING
            and self.current_session is not None
        ):
            # Charging stopped but the car may still be plugged in.
            await self._async_end_session(END_REASON_CHARGING_STOPPED)

    async def _async_handle_plug_sensor(self, event: Event) -> None:
        new_state = event.data["new_state"]
        if new_state is None:
            return
        if new_state.state == PLUG_STATE_DISCONNECTED:
            if self.current_session is not None:
                await self._async_end_session(END_REASON_DISCONNECTED)
            else:
                # No active session, but state may have been "connected_idle" — nothing to persist.
                async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")
        elif new_state.state == PLUG_STATE_CONNECTED:
            async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    async def _async_start_session(self, recovered: bool = False) -> None:
        now = dt_util.now()
        session_id = f"ses_{now.strftime('%Y%m%d_%H%M%S')}"
        session = {
            "id": session_id,
            "start": now.isoformat(),
            "end": None,
            "energy_start_kwh": _float_state(self.hass, self.energy_sensor),
            "energy_end_kwh": None,
            "energy_kwh": None,
            "end_reason": None,
            "mode_at_start": _raw_state(self.hass, self.mode_entity),
            "current_a_at_start": _float_state(self.hass, self.current_sensor),
            "recovered": recovered,
            "reconciled": False,
        }
        self.sessions.append(session)
        await self._async_save()
        _LOGGER.info("SmartEVSE session %s started", session_id)
        if recovered:
            await self.async_notify(
                f"⚠️ {self.entry.data.get(CONF_NAME, 'SmartEVSE')} logging herstel",
                (
                    f"De EVSE was aan het laden maar er liep geen sessie-registratie "
                    f"(bijv. na een herstart). Sessie {session_id} is automatisch hersteld, "
                    f"maar het startpunt (kWh/tijd) kan afwijken van de werkelijke laadstart."
                ),
            )

    async def _async_end_session(self, reason: str) -> None:
        session = self.current_session
        if session is None:
            return
        now = dt_util.now()
        end_kwh = _float_state(self.hass, self.energy_sensor)
        session["end"] = now.isoformat()
        session["energy_end_kwh"] = end_kwh
        if end_kwh is not None and session.get("energy_start_kwh") is not None:
            session["energy_kwh"] = round(end_kwh - session["energy_start_kwh"], 3)
        session["end_reason"] = reason
        await self._async_save()
        _LOGGER.info(
            "SmartEVSE session %s ended (%s), %s kWh",
            session["id"],
            reason,
            session.get("energy_kwh"),
        )

    # ------------------------------------------------------------------ #
    # Watchdog — safety net in case a state-change event was ever missed
    # ------------------------------------------------------------------ #
    async def async_run_watchdog(self, now: datetime) -> None:
        if self.current_session is not None:
            return
        if _raw_state(self.hass, self.state_sensor) == EVSE_STATE_CHARGING:
            _LOGGER.warning(
                "Watchdog: %s reports Charging but no session is active — recovering",
                self.state_sensor,
            )
            await self._async_start_session(recovered=True)

    # ------------------------------------------------------------------ #
    # Reconciliation
    # ------------------------------------------------------------------ #
    async def async_run_reconciliation(self, now: datetime) -> None:
        total_sensor = self.total_energy_sensor
        if not total_sensor:
            _LOGGER.debug("Reconciliation skipped: no total-energy sensor configured")
            return

        total_now = _float_state(self.hass, total_sensor)
        if total_now is None:
            _LOGGER.warning(
                "Reconciliation skipped: %s is unavailable right now", total_sensor
            )
            return

        recon = self.reconciliation
        ended_sessions = [s for s in self.sessions if s.get("end") is not None]
        unreconciled = [s for s in ended_sessions if not s.get("reconciled")]

        report_lines: list[str] = []
        corrected = 0
        unresolved = 0

        if recon.get("last_total_energy_kwh") is None:
            # First run ever: establish a baseline, don't second-guess history we
            # have no ground truth for.
            for session in unreconciled:
                session["reconciled"] = True
            recon["last_total_energy_kwh"] = total_now
            recon["last_reconciled_session_id"] = (
                unreconciled[-1]["id"] if unreconciled else None
            )
            report_lines.append(
                f"Eerste controle: basislijn vastgelegd op {total_now:.3f} kWh "
                f"({len(unreconciled)} sessie(s) als uitgangspunt geaccepteerd)."
            )
        elif unreconciled:
            baseline = recon["last_total_energy_kwh"]
            expected = baseline + sum(
                s.get("energy_kwh") or 0 for s in unreconciled
            )
            diff = round(total_now - expected, 3)
            tolerance = self._opt(CONF_RECONCILE_TOLERANCE, 0.02)

            if abs(diff) <= tolerance:
                report_lines.append(
                    f"{len(unreconciled)} sessie(s) gecontroleerd, geen afwijking "
                    f"(verschil {diff:+.3f} kWh, binnen tolerantie {tolerance} kWh)."
                )
            elif len(unreconciled) == 1:
                session = unreconciled[0]
                session["energy_kwh_raw"] = session.get("energy_kwh")
                session["energy_kwh"] = round((session.get("energy_kwh") or 0) + diff, 3)
                session["reconciliation_corrected"] = True
                corrected = 1
                report_lines.append(
                    f"Sessie {session['id']}: {diff:+.3f} kWh gecorrigeerd op basis van "
                    f"de EVSE-totaalteller ({total_sensor})."
                )
            else:
                unresolved = len(unreconciled)
                report_lines.append(
                    f"Afwijking van {diff:+.3f} kWh over {len(unreconciled)} sessies sinds "
                    f"de laatste controle — kan niet automatisch aan één sessie worden "
                    f"toegeschreven. Controleer handmatig."
                )
                for session in unreconciled:
                    session["reconciliation_unresolved"] = True

            for session in unreconciled:
                session["reconciled"] = True
            recon["last_total_energy_kwh"] = total_now
            recon["last_reconciled_session_id"] = unreconciled[-1]["id"]
        else:
            report_lines.append("Geen nieuwe sessies sinds de vorige controle.")

        recon["last_run"] = now.isoformat()
        recon["corrected_count"] = corrected
        recon["unresolved_count"] = unresolved
        recon["report_text"] = "\n".join(report_lines)
        await self._async_save()

        if corrected or unresolved:
            title = (
                f"SmartEVSE sessiecontrole: {corrected} correctie(s), "
                f"{unresolved} onopgelost ({now.strftime('%d-%m-%Y')})"
            )
            await self.async_notify(title, recon["report_text"])
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": title,
                    "message": recon["report_text"],
                    "notification_id": f"{DOMAIN}_{self.entry.entry_id}_reconcile",
                },
            )

    # ------------------------------------------------------------------ #
    # CSV export
    # ------------------------------------------------------------------ #
    def _sessions_in_range(
        self, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        result = []
        for session in self.sessions:
            try:
                session_start = dt_util.parse_datetime(session["start"])
            except (KeyError, TypeError, ValueError):
                continue
            if session_start is None:
                continue
            if start <= session_start < end:
                result.append(session)
        return result

    @staticmethod
    def _duration_str(session: dict[str, Any]) -> str:
        start = dt_util.parse_datetime(session["start"]) if session.get("start") else None
        end = dt_util.parse_datetime(session["end"]) if session.get("end") else None
        if not start or not end:
            return ""
        seconds = int((end - start).total_seconds())
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        return f"{hours}:{minutes:02d}"

    def build_csv(self, start: datetime, end: datetime) -> tuple[str, list[dict[str, Any]]]:
        sessions = self._sessions_in_range(start, end)
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(
            [
                "Sessie ID",
                "Start",
                "Einde",
                "Duur",
                "Start (kWh MID)",
                "Einde (kWh MID)",
                "Geladen (kWh)",
                "Reden einde",
                "Modus bij start",
                "Stroom bij start (A)",
                "Hersteld",
                "Gecorrigeerd",
            ]
        )
        for session in sessions:
            writer.writerow(
                [
                    session.get("id"),
                    session.get("start"),
                    session.get("end") or "",
                    self._duration_str(session),
                    session.get("energy_start_kwh"),
                    session.get("energy_end_kwh"),
                    session.get("energy_kwh"),
                    session.get("end_reason") or "",
                    session.get("mode_at_start") or "",
                    session.get("current_a_at_start") or "",
                    "ja" if session.get("recovered") else "",
                    "ja" if session.get("reconciliation_corrected") else "",
                ]
            )
        return buffer.getvalue(), sessions

    async def async_export_csv(self, start: datetime, end: datetime) -> dict[str, Any]:
        csv_text, sessions = self.build_csv(start, end)
        target_dir = Path(self.hass.config.path("www")) / EXPORT_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{self.slug}_{start.date()}_{end.date()}.csv"
        target_path = target_dir / filename

        def _write() -> None:
            target_path.write_text(csv_text, encoding="utf-8-sig")

        await self.hass.async_add_executor_job(_write)

        base_url = self.hass.config.external_url or self.hass.config.internal_url or ""
        url = f"{base_url}/local/{EXPORT_DIR}/{filename}" if base_url else f"/local/{EXPORT_DIR}/{filename}"

        total_kwh = round(sum(s.get("energy_kwh") or 0 for s in sessions), 3)
        return {
            "path": str(target_path),
            "url": url,
            "row_count": len(sessions),
            "total_kwh": total_kwh,
            "csv": csv_text,
        }

    # ------------------------------------------------------------------ #
    # Periodic (weekly/monthly) export + email
    # ------------------------------------------------------------------ #
    async def async_run_periodic_export(self, start: datetime, end: datetime, label: str) -> None:
        result = await self.async_export_csv(start, end)
        title = f"SmartEVSE laadsessies — {label}"
        message = (
            f"Overzicht {label}: {result['row_count']} sessie(s), "
            f"{result['total_kwh']} kWh totaal geladen.\n\n"
            f"Download: {result['url']}"
        )
        await self.async_notify(title, message)

    # ------------------------------------------------------------------ #
    # Notifications
    # ------------------------------------------------------------------ #
    async def async_notify(self, title: str, message: str) -> None:
        service = self.notify_service
        if not service:
            return
        domain, _, service_name = service.partition(".")
        if not domain or not service_name:
            _LOGGER.warning(
                "Ongeldige notify-service '%s' geconfigureerd, overslaan", service
            )
            return
        try:
            await self.hass.services.async_call(
                domain,
                service_name,
                {"title": title, "message": message},
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - never let a notify failure break logging
            _LOGGER.exception("Versturen van notificatie via %s mislukt", service)
