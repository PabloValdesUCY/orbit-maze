"""Record single gestures for Orbit Maze and keep calibration and validation separate."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import serial
from serial.tools import list_ports

from capture import ROOT, parse_data, prepare_recording, read_line, read_status
from motion_data import MAX_GAP_MS

GESTURES = {
    'translation': 'Slide sideways once (about 15 cm). Keep the OLED facing up and do not twist.',
    'rotation_left': 'Turn left once (about 25 degrees, seen from above). Keep the OLED facing up.',
    'rotation_right': 'Turn right once (about 25 degrees, seen from above). Keep the OLED facing up.',
}
ROUNDS = (
    ('translation', 'rotation_left', 'rotation_right'),
    ('rotation_right', 'translation', 'rotation_left'),
    ('rotation_left', 'rotation_right', 'translation'),
    ('translation', 'rotation_right', 'rotation_left'),
    ('rotation_left', 'translation', 'rotation_right'),
)
TRIALS = tuple((index, label) for index, labels in enumerate(ROUNDS, start=1) for label in labels)


def wait_for_port():
    print('Waiting for the LilyGO. Connect it by USB and close Orbit Maze or any serial monitor.', flush=True)
    busy_port = None
    while True:
        ports = [port.device for port in list_ports.comports() if (port.vid, port.pid) == (0x303A, 0x1001)]
        if len(ports) == 1:
            try:
                return serial.Serial(ports[0], 115200, timeout=.10, write_timeout=2)
            except serial.SerialException:
                if busy_port != ports[0]:
                    busy_port = ports[0]
                    print(f'{busy_port} is unavailable. Save and close Orbit Maze or the serial monitor.', flush=True)
        if len(ports) > 1:
            raise ValueError('Multiple LilyGO devices found. Use --port to choose one.')
        if not ports:
            busy_port = None
        time.sleep(1)


def trial_identity(index, label):
    return {'file': f'{index:02d}_{label}.log', 'expected': label,
            'partition': 'calibration' if index <= 3 else 'validation'}


def resume_session(directory):
    manifest = json.loads((directory / 'session.json').read_text(encoding='utf-8'))
    if manifest['status'] not in ('incomplete', 'complete') or len(manifest['trials']) > len(TRIALS):
        raise ValueError('Invalid calibration session.')
    for item, (index, label) in zip(manifest['trials'], TRIALS):
        expected = trial_identity(index, label)
        if any(item.get(key) != value for key, value in expected.items()) or not (directory / expected['file']).is_file():
            raise ValueError('A saved trial is missing or out of order.')
    if manifest['status'] == 'complete' and len(manifest['trials']) != len(TRIALS):
        raise ValueError('The marked session is missing trials.')
    return manifest


def record_trial(port):
    print('Stay level and still until GO.', flush=True)
    prepare_recording(port)
    start = time.monotonic()
    frames = []
    last = None
    go = False
    go_ms = None
    while time.monotonic() - start < 3.1:
        if not go and time.monotonic() - start >= 1.65:
            print('GO! Make one gesture, then hold that position.', flush=True)
            go = True
        line = read_line(port)
        if line.startswith(('# USB_CONNECTED', '# SERIAL_GAP', '# DATA_GAP')):
            raise ValueError('A USB or sensor interruption occurred.')
        row = parse_data(line)
        if row is not None:
            if last is not None and not 0 < row[0] - last <= MAX_GAP_MS:
                raise ValueError('Samples did not arrive continuously.')
            last = row[0]
            if go and go_ms is None:
                go_ms = last
        if line.startswith(('DATA,', 'RESULT,')):
            frames.append(line)
    if go_ms is None or not frames:
        raise ValueError('No samples arrived during the movement.')
    return frames, go_ms


def record(port_name=None, directory=None):
    if directory is None:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        directory = ROOT / 'data' / 'game_calibration' / stamp
        directory.mkdir(parents=True, exist_ok=False)
        manifest = {'status': 'incomplete', 'trials': []}
    else:
        manifest = resume_session(directory)
    manifest_path = directory / 'session.json'

    def commit():
        temporary = manifest_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        temporary.replace(manifest_path)

    done = len(manifest['trials'])
    if done == len(TRIALS):
        manifest['status'] = 'complete'
        commit()
        return directory
    if done:
        print(f'Resuming with {done}/{len(TRIALS)} trials saved.', flush=True)
    connection = serial.Serial(port_name, 115200, timeout=.10, write_timeout=2) if port_name else wait_for_port()
    with connection as port:
        status = read_status(port)
        if not status['pmu_ready'] or not status['imu_ready'] or status['model_run_id'] == 'untrained':
            raise RuntimeError('The LilyGO needs its trained project firmware and a working IMU.')
        if done and manifest['device']['model_run_id'] != status['model_run_id']:
            raise RuntimeError('Reconnect the LilyGO with the project model used for the saved trials.')
        manifest['device'] = status
        commit()
        print('ORBIT MAZE • Single gesture calibration\n'
              'Move only when GO appears. Recenter your hand before starting each trial.\n', flush=True)
        for number, (index, label) in enumerate(TRIALS[done:], start=done+1):
            print(f'Trial {number}/{len(TRIALS)} — {GESTURES[label]}', flush=True)
            while True:
                input('Press Enter when the board is level and ready: ')
                try:
                    frames, go_ms = record_trial(port)
                except ValueError as error:
                    print(f'{error} Repeat this trial.', flush=True)
                    continue
                if input('Press Enter to keep this trial, or type R to repeat: ').strip().lower() != 'r':
                    break
            item = trial_identity(index, label)
            (directory / item['file']).write_text('\n'.join(frames) + '\n', encoding='utf-8')
            manifest['trials'].append({**item, 'go_ms': go_ms})
            commit()
    manifest['status'] = 'complete'
    commit()
    print(f'Calibration recordings saved: {directory}', flush=True)
    return directory


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='Use a specific LilyGO serial port')
    parser.add_argument('--resume', type=Path, help='Continue an existing calibration session')
    options = parser.parse_args()
    try:
        record(options.port, options.resume)
    except (OSError, RuntimeError, ValueError, KeyboardInterrupt, EOFError) as error:
        raise SystemExit(f'Calibration stopped: {error}')
