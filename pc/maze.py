"""Play Orbit Maze with the LilyGO or the keyboard."""
import argparse
from functools import partial
import socket
import time
import tkinter as tk

import serial
from serial.tools import list_ports

from capture import parse_data, parse_status, read_line, read_status
from game_input import GameInput, load_profile
from maze_app import OrbitMazeApp
from motion_data import LABELS, MAX_GAP_MS

WIFI_HOST = '192.168.4.1'
WIFI_PORT = 8765
WIFI_IDLE_TIMEOUT = 2.5
MAX_FRAME_BYTES = 160


def parse_result(line):
    fields = line.split(',')
    if len(fields) != 3 or fields[0] != 'RESULT':
        return None
    try:
        class_id, timestamp = map(int, fields[1:])
    except ValueError:
        return None
    if not 0 <= timestamp <= 0xFFFFFFFF or not -1 <= class_id < len(LABELS):
        return None
    return (None if class_id == -1 else LABELS[class_id]), timestamp


def read_board(port_name, messages, stop):
    """Read the LilyGO over its USB serial port."""
    with serial.Serial(port_name, 115200, timeout=0.1, write_timeout=2) as port:
        lines = iter(lambda: read_line(port), None)
        consume_frames(lines, read_status(port), port_name, messages, stop)


def consume_frames(lines, status, device, messages, stop):
    """Apply the same gesture detector to either transport off the Tk thread."""
    if not status['pmu_ready'] or not status['imu_ready']:
        raise RuntimeError('The IMU could not start. Check the board.')
    if status['model_run_id'] == 'untrained':
        raise RuntimeError('The LilyGO needs the trained project firmware.')
    messages.put(('connected', (device, status['model_run_id'])))
    motion = GameInput(load_profile())
    previous_sample = previous_result = None
    for line in lines:
        if stop.is_set():
            return
        if line in ('# USB_CONNECTED', '# DATA_GAP', '# SERIAL_GAP', '# WINDOW_RESET'):
            motion.reset()
            previous_sample = previous_result = None
            messages.put(('interrupted', None))
            continue
        try:
            sample = parse_data(line)
        except ValueError:
            motion.reset()
            previous_sample = previous_result = None
            messages.put(('interrupted', None))
            continue
        if sample is not None:
            timestamp = sample[0]
            if previous_sample is not None and not 0 < timestamp - previous_sample <= MAX_GAP_MS:
                motion.reset()
                previous_result = None
                messages.put(('interrupted', None))
            previous_sample = timestamp
            was_tracking = motion.burst is not None
            gesture = motion.feed(sample)
            if gesture:
                messages.put(('gesture', gesture))
            tracking = motion.burst is not None
            if tracking != was_tracking:
                messages.put(('activity', tracking))
            continue
        result = parse_result(line)
        if result is None:
            continue
        label, timestamp = result
        if timestamp == previous_result:
            continue
        if label is None or (previous_result is not None and timestamp < previous_result):
            motion.reset()
            messages.put(('interrupted', None))
        previous_result = timestamp
        motion.observe_prediction(label, timestamp)
        messages.put(('heartbeat', None))


def wireless_frames(connection, stop):
    buffer = b''
    last_frame = time.monotonic()
    while not stop.is_set():
        try:
            chunk = connection.recv(2048)
        except socket.timeout:
            chunk = None
        if chunk == b'':
            raise ConnectionError('The LilyGO ended the Wi-Fi stream.')
        if chunk:
            frames = (buffer + chunk).split(b'\n')
            buffer = frames.pop()
            if len(buffer) > MAX_FRAME_BYTES or any(len(frame) > MAX_FRAME_BYTES for frame in frames):
                raise RuntimeError('The Wi-Fi stream returned an invalid frame.')
            for frame in frames:
                last_frame = time.monotonic()
                yield frame.decode('ascii', errors='replace').strip()
        if time.monotonic() - last_frame > WIFI_IDLE_TIMEOUT:
            raise TimeoutError('The LilyGO stopped streaming over Wi-Fi.')


def read_wireless(host, messages, stop, port=WIFI_PORT):
    with socket.create_connection((host, port), timeout=1.5) as connection:
        connection.settimeout(.2)
        lines = wireless_frames(connection, stop)
        status = parse_status(next(lines, ''))
        if stop.is_set():
            return
        if status is None:
            raise RuntimeError('The Wi-Fi stream did not identify a LilyGO.')
        consume_frames(lines, status, 'Wi-Fi', messages, stop)


def watch_wireless(host, messages, stop):
    while not stop.is_set():
        try:
            read_wireless(host, messages, stop)
        except OSError:
            messages.put(('unavailable', 'Join the OrbitMaze Wi-Fi network to connect your LilyGO.'))
        except RuntimeError as error:
            messages.put(('unavailable', str(error)))
        else:
            return
        stop.wait(1)


def watch_board(preferred_port, messages, stop):
    """Attach to a matching ESP32 USB device when it becomes available."""
    previous_status = None
    while not stop.is_set():
        ports = [port.device for port in list_ports.comports()
                 if (port.vid, port.pid) == (0x303A, 0x1001)
                 and (preferred_port is None or port.device == preferred_port)]
        if len(ports) != 1:
            status = ('searching', 'More than one board found. Select a port with --port.' if ports else '')
        else:
            # A new attempt may connect and disconnect before raising the same error again.
            previous_status = None
            try:
                read_board(ports[0], messages, stop)
            except OSError:
                status = ('unavailable', f'Cannot open {ports[0]}. Close other serial apps or reconnect the LilyGO.')
            except RuntimeError as error:
                status = ('unavailable', str(error))
            else:
                return
        if status != previous_status:
            messages.put(status)
            previous_status = status
        stop.wait(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--port', help='Use a specific verified LilyGO serial port')
    mode.add_argument('--wifi', nargs='?', const=WIFI_HOST, metavar='HOST',
                      help=f'Use the LilyGO Wi-Fi stream (default host: {WIFI_HOST})')
    mode.add_argument('--keyboard', action='store_true', help='Play with Q, R and F without opening a serial port')
    args = parser.parse_args()
    root = tk.Tk()
    reader = None
    if args.wifi:
        reader = partial(watch_wireless, args.wifi)
    elif not args.keyboard:
        reader = partial(watch_board, args.port)
    OrbitMazeApp(root, reader, wireless=args.wifi is not None)
    root.mainloop()


if __name__ == '__main__':
    main()
