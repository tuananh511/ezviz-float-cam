"""tests/test_preroll.py — recording/preroll.py (thuần) + PreRollBuffer (VLC giả)."""

from pathlib import Path

import pytest

from recording.preroll import (
    SEG_LEN_S,
    TS_PACKET,
    build_buffer_sout,
    clear_buffer_dir,
    list_segments,
    num_segments_for,
    read_clip,
    select_recent_segments,
)

RTSP = {"ip": "1.2.3.4", "port": 554, "username": "a", "password": "b",
        "stream_type": "main", "channel": "ch1"}


def make_segs(d: Path, sizes):
    d.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, size in enumerate(sizes, 1):
        p = d / f"seg-{i:08d}.ts"
        p.write_bytes(bytes([i % 256]) * size)
        paths.append(p)
    return paths


# ---------------- logic thuần ----------------


def test_num_segments_covers_preroll_with_spare_segments():
    assert num_segments_for(1) == 4            # ceil(1/2) + 3 đoạn dự phòng
    assert num_segments_for(6) == 6
    assert num_segments_for(30) == 18
    assert num_segments_for(10) > num_segments_for(4)


def test_buffer_sout_quotes_paths_and_uses_forward_slashes():
    sout = build_buffer_sout("C:\\Users\\Han akomon\\AppData\\Local\\Temp\\EzvizFloatCam\\preroll", 6)
    assert "\\" not in sout
    assert 'index="C:/Users/Han akomon/AppData/Local/Temp/EzvizFloatCam/preroll/index.m3u8"' in sout
    assert 'dst="C:/Users/Han akomon/AppData/Local/Temp/EzvizFloatCam/preroll/seg-########.ts"' in sout
    assert f"seglen={SEG_LEN_S}" in sout and "delsegs=true" in sout
    assert f"numsegs={num_segments_for(6)}" in sout
    assert "mux=ts{use-key-frames}" in sout
    assert sout.startswith("#std{access=livehttp{") and sout.endswith("}")


def test_list_segments_sorted_and_ignores_other_files(tmp_path):
    make_segs(tmp_path, [10, 10, 10])
    (tmp_path / "index.m3u8").write_text("x")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "seg-abc.ts").write_text("x")
    names = [p.name for p in list_segments(tmp_path)]
    assert names == ["seg-00000001.ts", "seg-00000002.ts", "seg-00000003.ts"]


def test_list_segments_missing_dir(tmp_path):
    assert list_segments(tmp_path / "nope") == []


def test_select_recent_skips_empty_and_takes_newest(tmp_path):
    paths = make_segs(tmp_path, [100, 100, 100, 100, 0])   # đoạn cuối đang mở, rỗng
    chosen = select_recent_segments(paths, pre_roll_s=4)   # 4s / 2s = 2 đoạn
    assert [p.name for p in chosen] == ["seg-00000003.ts", "seg-00000004.ts"]


def test_select_recent_with_fewer_segments_than_needed(tmp_path):
    paths = make_segs(tmp_path, [100])
    assert len(select_recent_segments(paths, pre_roll_s=20)) == 1


def test_read_clip_concatenates_and_trims_to_ts_packets(tmp_path):
    a, b = make_segs(tmp_path, [TS_PACKET * 3, TS_PACKET * 2 + 50])
    data = read_clip([a, b])
    assert len(data) == TS_PACKET * 3 + TS_PACKET * 2
    assert data[: TS_PACKET * 3] == bytes([1]) * (TS_PACKET * 3)
    assert data[TS_PACKET * 3:] == bytes([2]) * (TS_PACKET * 2)


def test_read_clip_skips_missing_files(tmp_path):
    (a,) = make_segs(tmp_path, [TS_PACKET])
    assert read_clip([tmp_path / "gone.ts", a]) == bytes([1]) * TS_PACKET


def test_read_clip_empty(tmp_path):
    assert read_clip([]) == b""


def test_clear_buffer_dir_only_removes_buffer_files(tmp_path):
    make_segs(tmp_path, [10, 10])
    (tmp_path / "index.m3u8").write_text("x")
    (tmp_path / "keep-me.txt").write_text("x")
    (tmp_path / "other.ts").write_text("x")
    assert clear_buffer_dir(tmp_path) == 3
    assert sorted(p.name for p in tmp_path.iterdir()) == ["keep-me.txt", "other.ts"]


# ---------------- PreRollBuffer (VLC giả) ----------------


@pytest.fixture
def buf(tmp_path, wired_vlc):
    from preroll_buffer import PreRollBuffer

    clock = {"t": 100.0}
    b = PreRollBuffer(buffer_dir=tmp_path / "buf", clock=lambda: clock["t"])
    b._test_clock = clock
    yield b
    b.shutdown()


def test_disabled_by_default_and_snapshot_is_empty(buf):
    assert buf.is_running() is False
    assert buf.snapshot(6) == b""


def test_configure_starts_vlc_with_sub_stream_and_rolling_sout(buf, wired_vlc):
    buf.configure(RTSP, 6)
    assert buf.is_running()
    url = wired_vlc.instance.media_new.call_args[0][0]
    assert "/sub/av_stream" in url                       # luôn luồng nhẹ
    options = [c[0][0] for c in wired_vlc.media.add_option.call_args_list]
    assert any(o.startswith(":sout=#std{access=livehttp{") for o in options)
    assert ":sout-keep" in options and ":no-audio" in options
    wired_vlc.media_player.play.assert_called_once()


def test_configure_zero_or_none_stops(buf, wired_vlc):
    buf.configure(RTSP, 6)
    buf.configure(RTSP, 0)
    assert buf.is_running() is False
    wired_vlc.media_player.stop.assert_called()
    buf.configure(RTSP, 6)
    buf.configure(None, 6)
    assert buf.is_running() is False


def test_configure_same_settings_does_not_restart(buf, wired_vlc):
    buf.configure(RTSP, 6)
    buf.configure(RTSP, 6)
    assert wired_vlc.media_player.play.call_count == 1


def test_configure_changed_seconds_restarts(buf, wired_vlc):
    buf.configure(RTSP, 6)
    buf.configure(RTSP, 10)
    assert wired_vlc.media_player.play.call_count == 2


def test_snapshot_returns_recent_segments(buf):
    buf.configure(RTSP, 4)
    make_segs(buf.buffer_dir, [TS_PACKET * 2] * 4)
    data = buf.snapshot(4)
    assert len(data) == TS_PACKET * 2 * 2               # 4s / 2s = 2 đoạn


def test_start_failure_is_contained_and_retried_after_backoff(buf, fake_vlc):
    fake_vlc.Instance.side_effect = RuntimeError("libvlc not found")
    buf.configure(RTSP, 6)
    assert buf.is_running() is False
    assert "libvlc" in buf.last_error


def test_watchdog_restarts_dead_player_after_backoff(buf, wired_vlc, fake_vlc):
    buf.configure(RTSP, 6)
    wired_vlc.media_player.get_state.return_value = fake_vlc.State.Ended
    buf._check()                                         # phát hiện chết -> dừng, hẹn thử lại
    assert buf.is_running() is False
    buf._check()                                         # chưa tới giờ thử lại
    assert buf.is_running() is False
    buf._test_clock["t"] += 20
    wired_vlc.media_player.get_state.return_value = fake_vlc.State.Playing
    buf._check()
    assert buf.is_running() is True


def test_leftover_segments_are_cleared_on_start(buf):
    make_segs(buf.buffer_dir, [100, 100])
    buf.configure(RTSP, 6)
    assert list_segments(buf.buffer_dir) == []


def test_shutdown_stops_and_cleans(buf, wired_vlc):
    buf.configure(RTSP, 6)
    make_segs(buf.buffer_dir, [100])
    buf.shutdown()
    assert buf.is_running() is False
    assert list_segments(buf.buffer_dir) == []
