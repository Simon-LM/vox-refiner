"""Unit tests for src/weather.py.

All HTTP calls are mocked: tests never hit the network. The cache file is
redirected to a temporary path per test.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

import src.weather as weather


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(weather, "_CACHE_FILE", tmp_path / "weather-cache.json")


def _resp(json_payload: dict, status: int = 200) -> MagicMock:
    """Build a fake requests.Response."""
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_payload
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(response=r)
    else:
        r.raise_for_status.return_value = None
    return r


def _geocode_payload(name="Paris", lat=48.8566, lon=2.3522, cc="FR"):
    return {"results": [{
        "name": name,
        "latitude": lat,
        "longitude": lon,
        "country_code": cc,
    }]}


_DEFAULT_CURRENT = {
    "time": "2026-05-22T15:00",
    "temperature_2m": 18.5,
    "precipitation": 0.0,
    "wind_speed_10m": 10.0,
    "weather_code": 1,
    "is_day": 1,
}

_DEFAULT_HOURLY = {
    "time": [f"2026-05-22T{h:02d}:00" for h in range(24)],
    "temperature_2m":           [12.0] * 24,
    "precipitation":            [0.0] * 24,
    "precipitation_probability":[10] * 24,
    "wind_speed_10m":           [8.0] * 24,
    "weather_code":             [1] * 24,
    # 0 between 21h and 06h, 1 the rest of the day
    "is_day":                   [0 if h < 6 or h >= 21 else 1 for h in range(24)],
}

_MISSING = object()


def _forecast_payload(*, tz="Europe/Paris", current=_MISSING, hourly=_MISSING):
    return {
        "latitude": 48.8566,
        "longitude": 2.3522,
        "timezone": tz,
        "current": _DEFAULT_CURRENT if current is _MISSING else current,
        "hourly": _DEFAULT_HOURLY if hourly is _MISSING else hourly,
    }


# ── _geocode ──────────────────────────────────────────────────────────────────


class TestGeocode:
    def test_returns_lat_lon_and_name(self):
        with patch.object(weather.requests, "get",
                          return_value=_resp(_geocode_payload())):
            lat, lon, name = weather._geocode("Paris")
        assert lat == 48.8566
        assert lon == 2.3522
        assert name == "Paris, FR"

    def test_cache_hit_skips_http(self):
        with patch.object(weather.requests, "get",
                          return_value=_resp(_geocode_payload())) as mock_get:
            weather._geocode("Paris")
            weather._geocode("Paris")
        assert mock_get.call_count == 1

    def test_unknown_location_raises(self):
        with patch.object(weather.requests, "get",
                          return_value=_resp({"results": []})):
            with pytest.raises(weather.WeatherError, match="Unknown location"):
                weather._geocode("Nowhereville")

    def test_network_error_raises(self):
        with patch.object(weather.requests, "get",
                          side_effect=requests.ConnectionError("offline")):
            with pytest.raises(weather.WeatherError, match="Geocoding failed"):
                weather._geocode("Paris")

    def test_case_insensitive_cache_key(self):
        with patch.object(weather.requests, "get",
                          return_value=_resp(_geocode_payload())) as mock_get:
            weather._geocode("Paris")
            weather._geocode("paris")
            weather._geocode("PARIS")
        assert mock_get.call_count == 1


# ── _fetch_forecast ──────────────────────────────────────────────────────────


class TestFetchForecast:
    def test_returns_full_response(self):
        with patch.object(weather.requests, "get",
                          return_value=_resp(_forecast_payload())):
            data = weather._fetch_forecast(48.8566, 2.3522)
        assert "current" in data
        assert "hourly" in data
        assert data["timezone"] == "Europe/Paris"

    def test_cache_hit_skips_http(self):
        with patch.object(weather.requests, "get",
                          return_value=_resp(_forecast_payload())) as mock_get:
            weather._fetch_forecast(48.8566, 2.3522)
            weather._fetch_forecast(48.8566, 2.3522)
        assert mock_get.call_count == 1

    def test_stale_cache_refetches(self, monkeypatch):
        # First fetch
        with patch.object(weather.requests, "get",
                          return_value=_resp(_forecast_payload())) as mock_get:
            weather._fetch_forecast(48.8566, 2.3522)
            assert mock_get.call_count == 1

        # Manually mark the cache entry as stale by rewinding `fetched_at`
        cache = weather._load_cache()
        key = next(iter(cache.keys()))
        cache[key]["fetched_at"] = (
            datetime.now(tz=timezone.utc) - timedelta(hours=2)
        ).isoformat()
        weather._save_cache(cache)

        with patch.object(weather.requests, "get",
                          return_value=_resp(_forecast_payload())) as mock_get:
            weather._fetch_forecast(48.8566, 2.3522)
            assert mock_get.call_count == 1

    def test_http_error_raises_weather_error(self):
        with patch.object(weather.requests, "get",
                          return_value=_resp({}, status=500)):
            with pytest.raises(weather.WeatherError, match="Forecast fetch failed"):
                weather._fetch_forecast(48.8566, 2.3522)


# ── get_current ──────────────────────────────────────────────────────────────


class TestGetCurrent:
    def test_returns_snapshot(self):
        responses = iter([_resp(_geocode_payload()), _resp(_forecast_payload())])
        with patch.object(weather.requests, "get", side_effect=lambda *a, **kw: next(responses)):
            snap = weather.get_current("Paris")
        assert snap["location"] == "Paris, FR"
        assert snap["temperature_c"] == 18.5
        assert snap["weather_code"] == 1
        assert snap["weather_description"] == "Mainly clear"
        assert snap["precipitation_probability"] is None  # not in `current` block

    def test_is_day_propagated_to_snapshot(self):
        responses = iter([_resp(_geocode_payload()), _resp(_forecast_payload())])
        with patch.object(weather.requests, "get", side_effect=lambda *a, **kw: next(responses)):
            snap = weather.get_current("Paris")
        assert snap["is_day"] is True

    def test_is_day_false_when_api_returns_zero(self):
        forecast = _forecast_payload(current={
            "time": "2026-05-22T03:00",
            "temperature_2m": 10.0,
            "precipitation": 0.0,
            "wind_speed_10m": 5.0,
            "weather_code": 1,
            "is_day": 0,
        })
        responses = iter([_resp(_geocode_payload()), _resp(forecast)])
        with patch.object(weather.requests, "get", side_effect=lambda *a, **kw: next(responses)):
            snap = weather.get_current("Paris")
        assert snap["is_day"] is False

    def test_is_day_none_when_api_omits_field(self):
        forecast = _forecast_payload(current={
            "time": "2026-05-22T15:00",
            "temperature_2m": 18.0,
            "precipitation": 0.0,
            "wind_speed_10m": 5.0,
            "weather_code": 1,
            # is_day intentionally absent
        })
        responses = iter([_resp(_geocode_payload()), _resp(forecast)])
        with patch.object(weather.requests, "get", side_effect=lambda *a, **kw: next(responses)):
            snap = weather.get_current("Paris")
        assert snap["is_day"] is None

    def test_handles_unknown_weather_code(self):
        forecast = _forecast_payload(current={
            "time": "2026-05-22T15:00",
            "temperature_2m": 10.0,
            "precipitation": 0.0,
            "wind_speed_10m": 5.0,
            "weather_code": 999,  # nonsense code
            "is_day": 1,
        })
        responses = iter([_resp(_geocode_payload()), _resp(forecast)])
        with patch.object(weather.requests, "get", side_effect=lambda *a, **kw: next(responses)):
            snap = weather.get_current("Paris")
        assert snap["weather_description"] == "Unknown"

    def test_propagates_geocode_failure(self):
        with patch.object(weather.requests, "get",
                          return_value=_resp({"results": []})):
            with pytest.raises(weather.WeatherError):
                weather.get_current("Atlantis")


# ── get_forecast ─────────────────────────────────────────────────────────────


class TestGetForecast:
    def test_returns_snapshot_for_specific_hour(self):
        hourly = {
            "time": ["2026-05-23T08:00", "2026-05-23T09:00", "2026-05-23T10:00"],
            "temperature_2m":           [10.0, 14.0, 18.0],
            "precipitation":            [0.0, 0.5, 0.0],
            "precipitation_probability":[10, 20, 5],
            "wind_speed_10m":           [5.0, 8.0, 12.0],
            "weather_code":             [1, 2, 3],
        }
        forecast = _forecast_payload(tz="UTC", hourly=hourly)
        responses = iter([_resp(_geocode_payload()), _resp(forecast)])
        with patch.object(weather.requests, "get", side_effect=lambda *a, **kw: next(responses)):
            when = datetime(2026, 5, 23, 9, 0, tzinfo=timezone.utc)
            snap = weather.get_forecast("Paris", when)
        assert snap["as_of"] == "2026-05-23T09:00"
        assert snap["temperature_c"] == 14.0
        assert snap["precipitation_probability"] == 20

    def test_picks_closest_hour_when_exact_missing(self):
        hourly = {
            "time": ["2026-05-23T08:00", "2026-05-23T10:00"],
            "temperature_2m":           [10.0, 18.0],
            "precipitation":            [0.0, 0.0],
            "precipitation_probability":[10, 5],
            "wind_speed_10m":           [5.0, 12.0],
            "weather_code":             [1, 2],
        }
        forecast = _forecast_payload(tz="UTC", hourly=hourly)
        responses = iter([_resp(_geocode_payload()), _resp(forecast)])
        with patch.object(weather.requests, "get", side_effect=lambda *a, **kw: next(responses)):
            # 09:30 → equidistant; min() picks first index
            when = datetime(2026, 5, 23, 9, 30, tzinfo=timezone.utc)
            snap = weather.get_forecast("Paris", when)
        assert snap["as_of"] in ("2026-05-23T08:00", "2026-05-23T10:00")

    def test_raises_when_no_hourly_data(self):
        forecast = _forecast_payload(hourly={})
        responses = iter([_resp(_geocode_payload()), _resp(forecast)])
        with patch.object(weather.requests, "get", side_effect=lambda *a, **kw: next(responses)):
            with pytest.raises(weather.WeatherError, match="No hourly forecast"):
                weather.get_forecast("Paris", datetime(2026, 5, 23, 9, 0, tzinfo=timezone.utc))


# ── is_good_weather ──────────────────────────────────────────────────────────


class TestIsGoodWeather:
    def _snap(self, **overrides):
        base = {
            "weather_code": 1,
            "precipitation_mm": 0.0,
            "precipitation_probability": 10,
            "wind_speed_kmh": 8.0,
            "temperature_c": 20.0,
        }
        base.update(overrides)
        return base

    def test_clear_sky_is_good(self):
        assert weather.is_good_weather(self._snap(weather_code=0)) is True

    def test_overcast_is_good(self):
        assert weather.is_good_weather(self._snap(weather_code=3)) is True

    def test_rain_code_not_good(self):
        assert weather.is_good_weather(self._snap(weather_code=63)) is False

    def test_thunderstorm_not_good(self):
        assert weather.is_good_weather(self._snap(weather_code=95)) is False

    def test_significant_precipitation_not_good(self):
        assert weather.is_good_weather(self._snap(precipitation_mm=1.5)) is False

    def test_high_precipitation_probability_not_good(self):
        assert weather.is_good_weather(self._snap(precipitation_probability=80)) is False

    def test_high_wind_not_good(self):
        assert weather.is_good_weather(self._snap(wind_speed_kmh=45.0)) is False

    def test_freezing_temperature_not_good(self):
        assert weather.is_good_weather(self._snap(temperature_c=-2.0)) is False

    def test_heatwave_not_good(self):
        assert weather.is_good_weather(self._snap(temperature_c=40.0)) is False

    def test_empty_snapshot_not_good(self):
        assert weather.is_good_weather({}) is False
        assert weather.is_good_weather(None) is False  # type: ignore[arg-type]

    def test_missing_signals_default_to_good(self):
        # Defensive: if Open-Meteo omits a field, it should not block the call
        assert weather.is_good_weather({"weather_code": 1}) is True
