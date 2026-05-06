"""Unit tests for src/web_display.py — _Broadcaster and helper functions.

Covers:
  _Broadcaster.add_client()     — returns queue, replays cached events in order
  _Broadcaster.remove_client()  — removes client, no error on unknown queue
  _Broadcaster.broadcast()      — stores last events per type, delivers to clients,
                                  unknown type delivered but not cached,
                                  full queue silently dropped, new init resets replay
  _Broadcaster.close_all()      — sends None sentinel to all clients, full queue ignored
  _is_snap_binary()             — not found → False, /snap/ path → True, normal → False
  _flatpak_app_installed()      — absent dirs → False, present dir → True
  _vox_profile_dir()            — XDG_CACHE_HOME respected, dir created, name in path
"""

import os
import queue
from pathlib import Path
from unittest.mock import patch

import pytest

from src.web_display import (
    _Broadcaster,
    _flatpak_app_installed,
    _is_snap_binary,
    _vox_profile_dir,
)


# ---------------------------------------------------------------------------
# _Broadcaster.add_client
# ---------------------------------------------------------------------------

class TestAddClient:
    def test_returns_queue(self):
        b = _Broadcaster()
        q = b.add_client()
        assert isinstance(q, queue.Queue)

    def test_client_registered(self):
        b = _Broadcaster()
        b.add_client()
        assert len(b._clients) == 1

    def test_multiple_clients_all_registered(self):
        b = _Broadcaster()
        b.add_client()
        b.add_client()
        b.add_client()
        assert len(b._clients) == 3

    def test_no_prior_events_queue_empty(self):
        b = _Broadcaster()
        q = b.add_client()
        assert q.empty()

    def test_replays_init_on_late_connect(self):
        b = _Broadcaster()
        b.broadcast("init", '{"session":1}')
        q = b.add_client()
        item = q.get_nowait()
        assert item == ("init", '{"session":1}')

    def test_replays_chunk_on_late_connect(self):
        b = _Broadcaster()
        b.broadcast("init", "i")
        b.broadcast("chunk", '{"index":2}')
        q = b.add_client()
        q.get_nowait()  # init
        item = q.get_nowait()
        assert item == ("chunk", '{"index":2}')

    def test_replays_display_chunks_on_late_connect(self):
        b = _Broadcaster()
        b.broadcast("init", "i")
        b.broadcast("display_chunks", '{"chunks":[]}')
        q = b.add_client()
        q.get_nowait()  # init
        item = q.get_nowait()
        assert item == ("display_chunks", '{"chunks":[]}')

    def test_replays_full_text_on_late_connect(self):
        b = _Broadcaster()
        b.broadcast("init", "i")
        b.broadcast("full_text", '"hello world"')
        q = b.add_client()
        q.get_nowait()  # init
        item = q.get_nowait()
        assert item == ("full_text", '"hello world"')

    def test_replay_order_init_display_chunks_full_text_chunk(self):
        b = _Broadcaster()
        b.broadcast("init", "i")
        b.broadcast("display_chunks", "dc")
        b.broadcast("full_text", "ft")
        b.broadcast("chunk", "c")
        q = b.add_client()
        items = [q.get_nowait() for _ in range(4)]
        assert items[0][0] == "init"
        assert items[1][0] == "display_chunks"
        assert items[2][0] == "full_text"
        assert items[3][0] == "chunk"

    def test_only_replays_latest_chunk(self):
        b = _Broadcaster()
        b.broadcast("init", "i")
        b.broadcast("chunk", "c1")
        b.broadcast("chunk", "c2")
        q = b.add_client()
        items = [q.get_nowait() for _ in range(2)]
        assert items[1] == ("chunk", "c2")

    def test_only_replays_latest_display_chunks(self):
        b = _Broadcaster()
        b.broadcast("init", "i")
        b.broadcast("display_chunks", "dc1")
        b.broadcast("display_chunks", "dc2")
        q = b.add_client()
        items = [q.get_nowait() for _ in range(2)]
        assert items[1] == ("display_chunks", "dc2")


# ---------------------------------------------------------------------------
# _Broadcaster.remove_client
# ---------------------------------------------------------------------------

class TestRemoveClient:
    def test_removes_registered_client(self):
        b = _Broadcaster()
        q = b.add_client()
        b.remove_client(q)
        assert len(b._clients) == 0

    def test_only_removes_matching_client(self):
        b = _Broadcaster()
        q1 = b.add_client()
        q2 = b.add_client()
        b.remove_client(q1)
        assert len(b._clients) == 1
        assert b._clients[0] is q2

    def test_remove_unknown_client_no_exception(self):
        b = _Broadcaster()
        phantom = queue.Queue()
        b.remove_client(phantom)  # must not raise

    def test_remove_already_removed_no_exception(self):
        b = _Broadcaster()
        q = b.add_client()
        b.remove_client(q)
        b.remove_client(q)  # second removal must not raise


# ---------------------------------------------------------------------------
# _Broadcaster.broadcast
# ---------------------------------------------------------------------------

class TestBroadcast:
    def test_event_delivered_to_connected_client(self):
        b = _Broadcaster()
        q = b.add_client()
        b.broadcast("chunk", '{"i":0}')
        item = q.get_nowait()
        assert item == ("chunk", '{"i":0}')

    def test_event_delivered_to_all_clients(self):
        b = _Broadcaster()
        queues = [b.add_client() for _ in range(4)]
        b.broadcast("chunk", "data")
        for q in queues:
            assert q.get_nowait() == ("chunk", "data")

    def test_init_stored_as_last_init(self):
        b = _Broadcaster()
        b.broadcast("init", "session_data")
        assert b._last_init == ("init", "session_data")

    def test_chunk_stored_as_last_chunk(self):
        b = _Broadcaster()
        b.broadcast("chunk", "c")
        assert b._last_chunk == ("chunk", "c")

    def test_display_chunks_stored(self):
        b = _Broadcaster()
        b.broadcast("display_chunks", "dc")
        assert b._last_display_chunks == ("display_chunks", "dc")

    def test_full_text_stored(self):
        b = _Broadcaster()
        b.broadcast("full_text", "ft")
        assert b._last_full_text == ("full_text", "ft")

    def test_new_init_resets_chunk_replay(self):
        b = _Broadcaster()
        b.broadcast("chunk", "old_chunk")
        b.broadcast("init", "new_session")
        assert b._last_chunk is None

    def test_new_init_resets_display_chunks_replay(self):
        b = _Broadcaster()
        b.broadcast("display_chunks", "old_dc")
        b.broadcast("init", "new_session")
        assert b._last_display_chunks is None

    def test_new_init_resets_full_text_replay(self):
        b = _Broadcaster()
        b.broadcast("full_text", "old_ft")
        b.broadcast("init", "new_session")
        assert b._last_full_text is None

    def test_unknown_event_type_delivered_not_cached(self):
        b = _Broadcaster()
        q = b.add_client()
        b.broadcast("unknown_type", "payload")
        assert q.get_nowait() == ("unknown_type", "payload")
        # Unknown type is not in any replay slot
        assert b._last_init is None
        assert b._last_chunk is None
        assert b._last_display_chunks is None
        assert b._last_full_text is None

    def test_full_queue_silently_dropped(self):
        b = _Broadcaster()
        small_q: queue.Queue = queue.Queue(maxsize=1)
        with b._lock:
            b._clients.append(small_q)
        small_q.put("fill_it")  # now full
        b.broadcast("chunk", '{}')  # must not raise
        assert small_q.get_nowait() == "fill_it"  # original item intact

    def test_no_clients_broadcast_is_noop(self):
        b = _Broadcaster()
        b.broadcast("init", "data")  # must not raise with no clients


# ---------------------------------------------------------------------------
# _Broadcaster.close_all
# ---------------------------------------------------------------------------

class TestCloseAll:
    def test_sends_none_sentinel_to_all_clients(self):
        b = _Broadcaster()
        queues = [b.add_client() for _ in range(3)]
        b.close_all()
        for q in queues:
            assert q.get_nowait() is None

    def test_close_all_with_no_clients_is_noop(self):
        b = _Broadcaster()
        b.close_all()  # must not raise

    def test_close_all_full_queue_silently_ignored(self):
        b = _Broadcaster()
        small_q: queue.Queue = queue.Queue(maxsize=1)
        with b._lock:
            b._clients.append(small_q)
        small_q.put("fill_it")  # now full
        b.close_all()  # must not raise
        assert small_q.get_nowait() == "fill_it"


# ---------------------------------------------------------------------------
# _is_snap_binary
# ---------------------------------------------------------------------------

class TestIsSnapBinary:
    def test_binary_not_found_returns_false(self):
        with patch("src.web_display.shutil.which", return_value=None):
            assert _is_snap_binary("nonexistent") is False

    def test_snap_path_returns_true(self):
        with patch("src.web_display.shutil.which", return_value="/snap/chromium/2799/usr/lib/chromium/chromium"):
            assert _is_snap_binary("chromium") is True

    def test_normal_binary_returns_false(self):
        with patch("src.web_display.shutil.which", return_value="/usr/bin/chromium"), \
             patch("src.web_display.os.path.realpath", return_value="/usr/bin/chromium"):
            assert _is_snap_binary("chromium") is False

    def test_symlink_resolves_to_snap_returns_true(self):
        with patch("src.web_display.shutil.which", return_value="/usr/bin/chromium"), \
             patch("src.web_display.os.path.realpath", return_value="/snap/chromium/usr/lib/chromium-browser/chromium"):
            assert _is_snap_binary("chromium") is True

    def test_symlink_resolves_to_snap_bin_snap_returns_true(self):
        with patch("src.web_display.shutil.which", return_value="/usr/bin/brave-browser"), \
             patch("src.web_display.os.path.realpath", return_value="/snap/bin/snap"):
            assert _is_snap_binary("brave-browser") is True

    def test_oserror_on_realpath_returns_false(self):
        with patch("src.web_display.shutil.which", return_value="/usr/bin/google-chrome"), \
             patch("src.web_display.os.path.realpath", side_effect=OSError("permission denied")):
            assert _is_snap_binary("google-chrome") is False


# ---------------------------------------------------------------------------
# _flatpak_app_installed
# ---------------------------------------------------------------------------

class TestFlatpakAppInstalled:
    def test_absent_dirs_returns_false(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        # Also mock os.path.isdir so any system-level Flatpak install is invisible
        with patch("src.web_display.os.path.isdir", return_value=False):
            assert _flatpak_app_installed("org.chromium.Chromium") is False

    def test_user_flatpak_dir_present_returns_true(self, monkeypatch, tmp_path):
        app_dir = tmp_path / "flatpak" / "app" / "org.chromium.Chromium"
        app_dir.mkdir(parents=True)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert _flatpak_app_installed("org.chromium.Chromium") is True

    def test_system_flatpak_dir_present_returns_true(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        with patch("src.web_display.os.path.isdir", side_effect=lambda p: "/var/lib/flatpak" in p):
            assert _flatpak_app_installed("com.brave.Browser") is True

    def test_different_app_id_not_found(self, monkeypatch, tmp_path):
        app_dir = tmp_path / "flatpak" / "app" / "org.chromium.Chromium"
        app_dir.mkdir(parents=True)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert _flatpak_app_installed("com.brave.Browser") is False


# ---------------------------------------------------------------------------
# _vox_profile_dir
# ---------------------------------------------------------------------------

class TestVoxProfileDir:
    def test_returns_string(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        result = _vox_profile_dir("chromium")
        assert isinstance(result, str)

    def test_name_in_result(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        result = _vox_profile_dir("brave")
        assert "brave" in result

    def test_ends_with_profile_suffix(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        result = _vox_profile_dir("edge")
        assert result.endswith("-profile")

    def test_directory_created(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        result = _vox_profile_dir("chromium")
        assert os.path.isdir(result)

    def test_xdg_cache_home_used(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        result = _vox_profile_dir("chromium")
        assert result.startswith(str(tmp_path))

    def test_vox_refiner_in_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        result = _vox_profile_dir("chromium")
        assert "vox-refiner" in result

    def test_different_names_produce_different_paths(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        a = _vox_profile_dir("chromium")
        b = _vox_profile_dir("brave")
        assert a != b
