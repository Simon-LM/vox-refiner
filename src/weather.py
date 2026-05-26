#!/usr/bin/env python3
"""VoxRefiner — weather lookups for the smart reminder picker.

Stable public API that hides the implementation choice (currently Open-Meteo:
free, no API key, worldwide). The picker queries this module with a location
name and a time, and gets back a structured snapshot it can filter on.
Internal backend can be swapped later without breaking the contract.

Public API
----------
    get_current(location)         -> dict           (current conditions snapshot)
    get_forecast(location, when)  -> dict           (hourly forecast at `when`)
    is_good_weather(snapshot)     -> bool           (simple heuristic)
    WeatherError                                    (raised on failures)

Snapshot shape (stable):
    {
      "location":                  "Paris, FR",
      "as_of":                     "2026-05-22T15:00",
      "temperature_c":             18.5,
      "precipitation_mm":          0.2,
      "precipitation_probability": 30,      ← may be None for `current`
      "wind_speed_kmh":            12.3,
      "weather_code":              1,
      "weather_description":       "Mainly clear",
      "is_day":                    True     ← None if the API omits it
    }

CLI (ad-hoc inspection)
-----------------------
    python -m src.weather current  "Paris"
    python -m src.weather forecast "Paris" "2026-05-23 14:00"
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_CACHE_FILE = Path("/tmp/vox-weather-cache.json")
_GEOCODE_TTL_SECONDS = 7 * 24 * 3600   # 7 days — coordinates don't move
_FORECAST_TTL_SECONDS = 30 * 60        # 30 minutes
_HTTP_TIMEOUT_SECONDS = 5

# WMO weather codes → short human-readable label.
_WEATHER_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class WeatherError(RuntimeError):
    """Raised when weather data cannot be retrieved or parsed."""


# ── Cache layer ───────────────────────────────────────────────────────────────


def _load_cache() -> dict:
    if not _CACHE_FILE.exists():
        return {}
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # cache is best-effort; weather still works without it


def _is_fresh(entry: dict, ttl_seconds: int) -> bool:
    fetched = entry.get("fetched_at")
    if not fetched:
        return False
    try:
        dt = datetime.fromisoformat(fetched)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(tz=timezone.utc) - dt) < timedelta(seconds=ttl_seconds)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ── Geocoding (city/place name → coordinates) ────────────────────────────────


def _geocode(location: str) -> tuple[float, float, str]:
    """Return (latitude, longitude, formatted_name) for *location*.

    Uses Open-Meteo's geocoding endpoint. Cached for 7 days.
    """
    key = f"geocode:{location.lower().strip()}"
    cache = _load_cache()
    entry = cache.get(key)
    if entry and _is_fresh(entry, _GEOCODE_TTL_SECONDS):
        r = entry["result"]
        return r["lat"], r["lon"], r["name"]

    try:
        resp = requests.get(
            _GEOCODE_URL,
            params={"name": location, "count": 1, "language": "fr", "format": "json"},
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise WeatherError(f"Geocoding failed for {location!r}: {exc}") from exc

    results = data.get("results") or []
    if not results:
        raise WeatherError(f"Unknown location: {location!r}")
    top = results[0]
    name_parts = [top.get("name"), top.get("country_code")]
    formatted = ", ".join(p for p in name_parts if p)
    payload = {"lat": top["latitude"], "lon": top["longitude"], "name": formatted}
    cache[key] = {"fetched_at": _now_iso(), "result": payload}
    _save_cache(cache)
    return payload["lat"], payload["lon"], payload["name"]


# ── Forecast fetch + cache ────────────────────────────────────────────────────


def _fetch_forecast(lat: float, lon: float) -> dict:
    """Fetch current + 3-day hourly forecast for (lat, lon). Cached for 30 min."""
    key = f"weather:{lat:.4f},{lon:.4f}"
    cache = _load_cache()
    entry = cache.get(key)
    if entry and _is_fresh(entry, _FORECAST_TTL_SECONDS):
        return entry["result"]

    try:
        resp = requests.get(
            _FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,precipitation,wind_speed_10m,weather_code,is_day",
                "hourly": ("temperature_2m,precipitation,precipitation_probability,"
                           "wind_speed_10m,weather_code,is_day"),
                "forecast_days": 3,
                "timezone": "auto",
            },
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise WeatherError(f"Forecast fetch failed: {exc}") from exc

    cache[key] = {"fetched_at": _now_iso(), "result": data}
    _save_cache(cache)
    return data


# ── Snapshot builders ────────────────────────────────────────────────────────


def _snapshot(name, as_of, temp_c, precip_mm, precip_prob, wind_kmh, code, is_day) -> dict:
    return {
        "location": name,
        "as_of": as_of,
        "temperature_c": temp_c,
        "precipitation_mm": precip_mm,
        "precipitation_probability": precip_prob,
        "wind_speed_kmh": wind_kmh,
        "weather_code": code,
        "weather_description": _WEATHER_CODES.get(code, "Unknown") if code is not None else "Unknown",
        "is_day": bool(is_day) if is_day is not None else None,
    }


def _at(hourly: dict, key: str, idx: int):
    series = hourly.get(key) or []
    return series[idx] if 0 <= idx < len(series) else None


# ── Public API ────────────────────────────────────────────────────────────────


def get_current(location: str) -> dict:
    """Return a snapshot of current weather at *location*.

    Raises WeatherError if geocoding or the forecast API fails.
    """
    lat, lon, name = _geocode(location)
    data = _fetch_forecast(lat, lon)
    current = data.get("current") or {}
    return _snapshot(
        name=name,
        as_of=current.get("time") or _now_iso(),
        temp_c=current.get("temperature_2m"),
        precip_mm=current.get("precipitation"),
        precip_prob=None,  # not in `current` block — see hourly forecast
        wind_kmh=current.get("wind_speed_10m"),
        code=current.get("weather_code"),
        is_day=current.get("is_day"),
    )


def get_forecast(location: str, when: datetime) -> dict:
    """Return a snapshot at the hour closest to *when* at *location*.

    *when* should be a timezone-aware datetime; naive datetimes are assumed UTC.
    Raises WeatherError if the forecast does not cover the requested time.
    """
    lat, lon, name = _geocode(location)
    data = _fetch_forecast(lat, lon)
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        raise WeatherError("No hourly forecast data available")

    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    tz_name = data.get("timezone", "UTC")
    try:
        from zoneinfo import ZoneInfo
        local = when.astimezone(ZoneInfo(tz_name))
    except Exception:  # noqa: BLE001 — fall back if zoneinfo unavailable
        local = when

    target = local.strftime("%Y-%m-%dT%H:00")
    if target in times:
        best_idx = times.index(target)
    else:
        try:
            target_dt = datetime.fromisoformat(target)
            best_idx = min(
                range(len(times)),
                key=lambda i: abs(datetime.fromisoformat(times[i]) - target_dt),
            )
        except ValueError as exc:
            raise WeatherError("Could not match the requested time in the forecast") from exc

    return _snapshot(
        name=name,
        as_of=times[best_idx],
        temp_c=_at(hourly, "temperature_2m", best_idx),
        precip_mm=_at(hourly, "precipitation", best_idx),
        precip_prob=_at(hourly, "precipitation_probability", best_idx),
        wind_kmh=_at(hourly, "wind_speed_10m", best_idx),
        code=_at(hourly, "weather_code", best_idx),
        is_day=_at(hourly, "is_day", best_idx),
    )


def is_good_weather(snapshot: dict) -> bool:
    """Heuristic: True if conditions are suitable for outdoor activity.

    Returns False when any signal is unfavourable: precipitation, high wind,
    extreme temperature, or a weather code beyond "overcast" (3).
    """
    if not snapshot:
        return False
    code = snapshot.get("weather_code")
    if code is not None and code not in (0, 1, 2, 3):
        return False
    precip = snapshot.get("precipitation_mm")
    if precip is not None and precip >= 1.0:
        return False
    prob = snapshot.get("precipitation_probability")
    if prob is not None and prob >= 50:
        return False
    wind = snapshot.get("wind_speed_kmh")
    if wind is not None and wind >= 30:
        return False
    temp = snapshot.get("temperature_c")
    if temp is not None and (temp < 0 or temp > 35):
        return False
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Weather lookups (Open-Meteo)")
    sub = parser.add_subparsers(dest="cmd")

    p_cur = sub.add_parser("current", help="Current weather at a location")
    p_cur.add_argument("location")

    p_fc = sub.add_parser("forecast", help="Hourly forecast at a location")
    p_fc.add_argument("location")
    p_fc.add_argument("when", help="ISO datetime (e.g. '2026-05-23 14:00')")

    args = parser.parse_args()
    try:
        if args.cmd == "current":
            snap = get_current(args.location)
            snap["is_good"] = is_good_weather(snap)
            print(json.dumps(snap, ensure_ascii=False, indent=2))
        elif args.cmd == "forecast":
            when = datetime.fromisoformat(args.when.replace(" ", "T"))
            snap = get_forecast(args.location, when)
            snap["is_good"] = is_good_weather(snap)
            print(json.dumps(snap, ensure_ascii=False, indent=2))
        else:
            parser.print_help(sys.stderr)
            sys.exit(1)
    except WeatherError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
