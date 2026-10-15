from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import app.media as media


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg required')
@pytest.mark.parametrize('video,audio', [('libx264', 'aac'), ('libx264', 'libopus'), ('libvpx-vp9', 'aac'), ('libvpx-vp9', 'libopus')])
def test_real_streams_copy_only_compatible_tracks(tmp_path, monkeypatch, video, audio):
    source = tmp_path / 'input.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=128x96:rate=10',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '1',
                    '-c:v', video, '-pix_fmt', 'yuv420p', '-c:a', audio, str(source)], check=True)
    def packet_hashes(path, stream):
        result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', stream,
                                 '-show_packets', '-show_data_hash', 'sha256',
                                 '-show_entries', 'packet=data_hash', '-of', 'json', str(path)],
                                check=True, capture_output=True, text=True)
        return [packet['data_hash'] for packet in json.loads(result.stdout)['packets']]
    original_video = packet_hashes(source, 'v:0')
    original_audio = packet_hashes(source, 'a:0')
    commands = []
    original = media._run_media_command
    def run(command, timeout):
        if Path(command[0]).name == 'ffmpeg':
            commands.append(command)
        return original(command, timeout)
    monkeypatch.setattr(media, '_run_media_command', run)
    output, delivery = media._normalize_video_for_delivery(source, require_audio=True)
    assert len(commands) == 1
    command = commands[0]
    assert command[command.index('-c:v') + 1] == ('copy' if video == 'libx264' else 'libx264')
    assert command[command.index('-c:a') + 1] == ('copy' if audio == 'aac' else 'aac')
    assert delivery['quicktime_compatible'] and delivery['audio_included']
    assert output.suffix == '.mp4'
    assert not source.exists()
    if video == 'libx264':
        assert packet_hashes(output, 'v:0') == original_video
    if audio == 'aac':
        assert packet_hashes(output, 'a:0') == original_audio
    # Decode the complete generated artifact, not just its container metadata.
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(output), '-f', 'null', '-'], check=True)
    data = output.read_bytes()
    assert data.index(b'moov') < data.index(b'mdat')


@pytest.mark.parametrize('failure', ['command', 'reported_corruption', 'invalid_output'])
def test_copy_failure_retries_full_conversion(tmp_path, monkeypatch, failure):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'original')
    probe = {'streams': [
        {'codec_type': 'video', 'codec_name': 'h264', 'profile': 'High', 'pix_fmt': 'yuv420p'},
        {'codec_type': 'audio', 'codec_name': 'aac', 'profile': 'LC'},
    ], 'format': {'duration': '1'}}
    commands = []
    def run(command, timeout):
        commands.append(command)
        assert source.read_bytes() == b'original'
        if len(commands) == 1 and failure == 'command':
            raise media.MediaServiceError('copy failed')
        Path(command[-1]).write_bytes(b'final')
        return subprocess.CompletedProcess(command, 0, '', 'corrupt packet' if len(commands) == 1 and failure == 'reported_corruption' else '')
    def inspect(path):
        if path != source and len(commands) == 1 and failure == 'invalid_output':
            return {'streams': []}
        return probe
    monkeypatch.setattr(media, '_probe_media', inspect)
    monkeypatch.setattr(media, '_run_media_command', run)
    monkeypatch.setattr(media.shutil, 'which', lambda name: name)
    output, _ = media._normalize_video_for_delivery(source, True)
    assert len(commands) == 2
    assert commands[0][commands[0].index('-c:v') + 1] == 'copy'
    assert commands[1][commands[1].index('-c:v') + 1] == 'libx264'
    assert commands[1][commands[1].index('-c:a') + 1] == 'aac'
    assert output.read_bytes() == b'final'
