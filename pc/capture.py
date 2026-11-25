"""Record labeled IMU sessions over USB at 115200 baud."""
import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from statistics import median
import time

import serial
from serial.tools import list_ports

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ('timestamp_ms', 'ax_g', 'ay_g', 'az_g', 'gx_dps', 'gy_dps', 'gz_dps')
GESTURES = {
    'rest': 'REST: hold the board still and level.',
    'rotation': 'ROTATION: turn the board gently left and right around the same point.',
    'translation': 'TRANSLATION: move the board gently from side to side while keeping its orientation.',
}


class InterruptedRecording(RuntimeError):
    """The current gesture cannot be used, but its serial port may recover."""


def parse_data(line):
    if not line.startswith('DATA,'):
        return None
    values = line.strip().split(',')
    if len(values) != 8:
        raise ValueError('Incomplete DATA frame')
    timestamp = int(values[1])
    axes = [float(value) for value in values[2:]]
    if not 0 <= timestamp <= 0xFFFFFFFF or not all(math.isfinite(value) for value in axes):
        raise ValueError('Invalid sample or timestamp')
    return [timestamp, *axes]


def read_line(port):
    return port.readline().decode('ascii', errors='replace').strip()


def read_status(port):
    port.reset_input_buffer()
    deadline = time.monotonic() + 3
    next_query = 0.0
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_query:
            port.write(b'?')
            next_query = now + 0.5
        line = read_line(port)
        if not line.startswith('STATUS,'):
            continue
        fields = line.split(',')
        if len(fields) != 6 or fields[1] != 'imu1' or not fields[2] or any(
            flag not in ('0', '1') for flag in fields[3:]
        ):
            raise RuntimeError(f'Unrecognized firmware status: {line}')
        return {
            'protocol': fields[1], 'model_run_id': fields[2], 'pmu_ready': fields[3] == '1',
            'imu_ready': fields[4] == '1', 'oled_initialized': fields[5] == '1',
        }
    raise RuntimeError('No STATUS from the board. Check the port and upload the current project firmware.')


def prepare_recording(port):
    # Drain the serial stream during the countdown to exclude earlier samples.
    for remaining in (3, 2, 1):
        print(f'Start in {remaining}...', flush=True)
        end = time.monotonic() + 1
        while time.monotonic() < end:
            read_line(port)
    port.reset_input_buffer()
    port.write(b'r')
    end = time.monotonic() + 3
    while time.monotonic() < end:
        if read_line(port) == '# WINDOW_RESET':
            return
    raise RuntimeError('No WINDOW_RESET acknowledgment. Check the port and upload the project firmware.')


def record_gesture(port, directory, label, seconds):
    prepare_recording(port)
    print(f'Recording {label} for {seconds:g} seconds. Keep performing the gesture.', flush=True)
    start = time.monotonic()
    last_arrival = start
    previous_timestamp = None
    count = 0
    gaps = 0
    with (directory / f'{label}.csv').open('x', newline='', encoding='utf-8') as handle, \
            (directory / f'{label}.log').open('x', encoding='utf-8') as log:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        while time.monotonic() - start < seconds:
            line = read_line(port)
            if line:
                log.write(line + '\n')
            if line.startswith('# SERIAL_GAP'):
                raise InterruptedRecording('Serial bytes were lost.')
            if line == '# USB_CONNECTED':
                raise InterruptedRecording('The USB connection restarted during recording.')
            try:
                row = parse_data(line)
            except ValueError as error:
                raise InterruptedRecording(str(error)) from error
            if row is not None:
                if previous_timestamp is not None:
                    if row[0] <= previous_timestamp:
                        raise InterruptedRecording('The board restarted or repeated a timestamp.')
                    gaps += int(row[0] - previous_timestamp > 100)
                previous_timestamp = row[0]
                last_arrival = time.monotonic()
                writer.writerow(row)
                count += 1
            if time.monotonic() - last_arrival > 3:
                raise InterruptedRecording('No valid DATA for three seconds.')
    elapsed = time.monotonic() - start
    if count < 500:
        raise InterruptedRecording(f'Only {count} samples recorded. A take needs at least 500 samples.')
    print(f'Saved {count} samples at {count / elapsed:.1f} samples/s with {gaps} gaps over 100 ms.')
    return {'samples': count, 'elapsed_seconds': elapsed, 'gaps_over_100ms': gaps}


def record_with_retry(port, directory, label, seconds):
    while True:
        try:
            return record_gesture(port, directory, label, seconds)
        except InterruptedRecording as error:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            interrupted = directory / 'interrupted' / f'{label}_{stamp}'
            interrupted.mkdir(parents=True, exist_ok=False)
            for suffix in ('csv', 'log'):
                source = directory / f'{label}.{suffix}'
                source.rename(interrupted / source.name)
            (interrupted / 'reason.txt').write_text(f'{error}\n', encoding='utf-8')
            print(f'Interrupted {label}: {error} The partial recording has been kept apart.')
            input(f'Check the USB cable and press Enter to retry {label}. ')


def check_device(port):
    destination = ROOT / 'data' / 'checks'
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.log')
    count = 0
    previous = None
    intervals = []
    with path.open('x', encoding='utf-8') as log:
        try:
            status = read_status(port)
        except RuntimeError as error:
            log.write(f'{error}\n')
            print(f'Diagnostic log saved to {path}')
            raise
        log.write(json.dumps(status) + '\n')
        print(f"Model: {status['model_run_id']}. PMU ready: {status['pmu_ready']}. IMU ready: {status['imu_ready']}. "
              f"OLED initialized: {status['oled_initialized']}.")
        end = time.monotonic() + 8
        while time.monotonic() < end:
            line = read_line(port)
            if not line:
                continue
            log.write(line + '\n')
            row = parse_data(line)
            if row:
                count += 1
                if previous is not None and row[0] > previous:
                    intervals.append(row[0] - previous)
                previous = row[0]
                if count <= 3:
                    print(line)
            elif not line.startswith('RESULT,'):
                print(line)
        if intervals:
            cadence = f'Median interval between samples: {median(intervals):g} ms'
            log.write(f'{cadence}\n')
            print(cadence)
    print(f'Diagnostic log saved to {path}\nValid samples: {count}')
    print('Check the OLED for visible text. The serial log only reports initialization.')
    if not count:
        raise RuntimeError('The project firmware returned no IMU samples.')


def capture_session(port, name, seconds):
    device = read_status(port)
    if not device['pmu_ready'] or not device['imu_ready']:
        raise RuntimeError('Power management or the IMU failed to initialize. Run --check.')
    directory = ROOT / 'data' / 'raw' / name
    directory.mkdir(parents=True, exist_ok=False)
    metadata = {'session': name, 'port': port.port, 'seconds_per_class': seconds,
                'status': 'incomplete', 'device': device, 'gestures': {}, 'notes': ''}
    path = directory / 'session.json'
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        print('Perform each gesture gently, keeping a consistent grip and leaving slack in the USB cable.')
        for label, instruction in GESTURES.items():
            print('\n' + instruction)
            input('Press Enter when ready to start the countdown. ')
            metadata['gestures'][label] = record_with_retry(port, directory, label, seconds)
            path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        metadata['notes'] = input('Session notes (grip, mistakes or interruptions): ')
        metadata['status'] = 'complete'
    finally:
        path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Session complete: {directory}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='List available serial ports')
    parser.add_argument('--port', help='Verified serial port for the board, for example COM3')
    parser.add_argument('--check', action='store_true', help='Save an eight-second diagnostic log')
    parser.add_argument('--seconds', type=float, default=30, help='Recording time per class in seconds (default: 30)')
    parser.add_argument('--session', help='Optional session name (default: UTC timestamp)')
    parser.add_argument('--sessions', type=int, default=1, help='Number of guided sessions to record (default: 1)')
    args = parser.parse_args()
    if args.list:
        ports = list(list_ports.comports())
        for item in ports:
            print(f'{item.device}\t{item.description}\t{item.hwid}')
        if not ports:
            print('No serial port detected. Connect the board with a USB data cable.')
        return
    if not args.port:
        parser.error('Check the board port with --list, then pass it to --port')
    if not 10 <= args.seconds <= 120:
        parser.error('--seconds must be between 10 and 120')
    if args.sessions < 1:
        parser.error('--sessions must be at least 1')
    if args.sessions > 1 and (args.session is not None or args.check):
        parser.error('--sessions cannot be combined with --session or --check')
    if args.session is not None and not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', args.session):
        parser.error('The session name may contain only letters, digits, hyphens and underscores')
    with serial.Serial(args.port, 115200, timeout=0.1, write_timeout=2) as port:
        if args.check:
            check_device(port)
            return
        for index in range(args.sessions):
            if index:
                input('\nSet the board down, pick it up again, then press Enter for the next session. ')
            if args.sessions > 1:
                print(f'Session {index + 1} of {args.sessions}')
            name = args.session or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            capture_session(port, name, args.seconds)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, serial.SerialException, KeyboardInterrupt, EOFError) as error:
        raise SystemExit(f'Capture stopped: {error} Previously saved data has been kept.')
