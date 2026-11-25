"""Detect one deliberate motion burst and distinguish a slide from a turn."""
from collections import deque
from dataclasses import dataclass
import json
from math import hypot, radians, sqrt
from pathlib import Path
from statistics import fmean


@dataclass(frozen=True)
class MotionProfile:
    decision_ms: int = 180
    turn_degrees: float = 2.4
    turn_per_g: float = 105.
    slide_rms_g: float = .0048
    yaw_sign: int = 1


PROFILE_PATH = Path(__file__).resolve().parents[1] / 'data' / 'orbit_profile.json'


def load_profile(path=PROFILE_PATH):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        profile = MotionProfile(**data['profile'])
        if (135 <= profile.decision_ms <= 250
                and 1.2 <= profile.turn_degrees <= 5
                and 30 <= profile.turn_per_g <= 220
                and .002 <= profile.slide_rms_g <= .018
                and profile.yaw_sign in (-1, 1)):
            return profile
    except (OSError, KeyError, TypeError, ValueError):
        pass
    return MotionProfile()


class MotionBurst:
    def __init__(self, timestamp, reference):
        self.start = self.last = timestamp
        self.reference = reference
        self.yaw = 0.
        self.yaw_travel = 0.
        self.residual_energy = 0.
        self.last_yaw_rate = 0.

    def add(self, timestamp, acceleration, rates):
        step = (timestamp-self.last) / 1000
        self.last = timestamp
        roll, pitch, yaw = rates
        self.last_yaw_rate = yaw
        self.yaw += yaw * step
        self.yaw_travel += abs(yaw) * step

        # During a short turn, predict how gravity projects into the board's
        # frame. The remaining horizontal acceleration is the slide evidence.
        gx, gy, gz = self.reference
        rx, ry, rz = map(radians, rates)
        self.reference = (gx + (rz*gy-ry*gz)*step,
                          gy + (rx*gz-rz*gx)*step,
                          gz + (ry*gx-rx*gy)*step)
        dx, dy = (acceleration[i]-self.reference[i] for i in range(2))
        self.residual_energy += (dx*dx + dy*dy) * step

    def classify(self, profile):
        duration = (self.last-self.start) / 1000
        if not duration:
            return None
        lateral = sqrt(self.residual_energy / duration)
        angle = abs(self.yaw)
        # Incidental yaw during a slide must not win just because it arrived first.
        turn_boundary = min(5.2, max(profile.turn_degrees, profile.turn_per_g*lateral))
        if angle >= turn_boundary and angle >= .72*self.yaw_travel:
            return 'rotation_left' if self.yaw*profile.yaw_sign > 0 else 'rotation_right'
        if lateral >= profile.slide_rms_g and angle < .92*turn_boundary:
            # A turn that is still building gets another short look.
            if (duration < (profile.decision_ms+80)/1000 and lateral < .035
                    and abs(self.last_yaw_rate) >= 10 and self.yaw*self.last_yaw_rate > 0):
                return None
            return 'translation'
        return None


class GameInput:
    """Arm once at rest; compare short inertial cues before choosing an action."""

    def __init__(self, profile=None):
        self.profile = profile or MotionProfile()
        self.reset()

    def reset(self):
        self.samples = deque(maxlen=22)
        self.gyro_bias = None
        self.level_acceleration = None
        self.startup_still_since = None
        self.prediction = None
        self.quiet_since = None
        self.tilt_since = None
        self.tilt_reported = False
        self.last_motion_at = None
        self.burst = None
        self.armed = False

    def observe_prediction(self, label, timestamp):
        self.prediction = label, timestamp

    def feed(self, row):
        timestamp = row[0]
        self.samples.append(row)
        if len(self.samples) < self.samples.maxlen:
            return None
        history = list(self.samples)
        anchor, recent = history[:-5], history[-5:]
        acceleration = tuple(fmean(sample[i] for sample in recent) for i in (1, 2, 3))
        reference = tuple(fmean(sample[i] for sample in anchor) for i in (1, 2, 3))
        ax, ay, vertical = acceleration
        lateral = hypot(ax-reference[0], ay-reference[1])
        rates = tuple(fmean(sample[i] for sample in recent) for i in (4, 5, 6))

        if self.gyro_bias is None:
            label, predicted_at = self.prediction or (None, 0)
            yaw_samples = [sample[6] for sample in history]
            if vertical < .9 or lateral > .0026 or max(yaw_samples)-min(yaw_samples) > .8:
                self.startup_still_since = None
                return None
            model_rest = label == 'rest' and 0 <= timestamp-predicted_at <= 1400
            if not model_rest:
                # A sustained level hold can establish the reference when the model's
                # longer window still contains movements made before the hold.
                spans = [max(row[axis] for row in history)-min(row[axis] for row in history)
                         for axis in range(1, 7)]
                if max(spans[:3]) > .012 or max(spans[3:]) > 2.5 or abs(rates[2]) > 4:
                    self.startup_still_since = None
                    return None
                if self.startup_still_since is None:
                    self.startup_still_since = timestamp
                if timestamp-self.startup_still_since < 220:
                    return None
            self.gyro_bias = rates
            self.level_acceleration = ax, ay

        roll, pitch, yaw = rates = tuple(rate-bias for rate, bias in zip(rates, self.gyro_bias))
        off_plane_rate = hypot(roll, pitch)
        if vertical < .62 and self.tilt_since is None:
            self.tilt_since = timestamp
        elif vertical >= .70:
            self.tilt_since = None
        if vertical < .90:
            self.quiet_since = None
            self.burst = None
            self.armed = False
            if self.tilt_since is not None and timestamp-self.tilt_since >= 480 and not self.tilt_reported:
                self.tilt_reported = True
                return 'menu'
            return None
        self.tilt_reported = False

        quiet = abs(yaw) < 2.1 and off_plane_rate < 3 and lateral < .0026
        if quiet and self.burst is None:
            self.gyro_bias = tuple(bias+.025*delta for bias, delta in zip(self.gyro_bias, rates))
            if self.quiet_since is None:
                self.quiet_since = timestamp
            offset = hypot(ax-self.level_acceleration[0], ay-self.level_acceleration[1])
            settle_ms = 700 if offset > .010 else 250
            elapsed = timestamp-self.last_motion_at if self.last_motion_at is not None else 400
            if timestamp-self.quiet_since >= settle_ms and elapsed >= 360:
                self.level_acceleration = ax, ay
                self.quiet_since = timestamp
                self.armed = True
                return 'rest'
        else:
            self.quiet_since = None

        if self.burst is None:
            if not self.armed or not (abs(yaw) >= 5 or (lateral >= .0043 and off_plane_rate < 12)):
                return None
            self.burst = MotionBurst(timestamp, reference)

        self.burst.add(timestamp, acceleration, rates)
        elapsed = timestamp-self.burst.start
        if elapsed < self.profile.decision_ms:
            return None
        action = self.burst.classify(self.profile)
        if action is None and elapsed < self.profile.decision_ms+100:
            return None
        self.last_motion_at = timestamp
        self.burst = None
        self.armed = False
        return action or 'unclear'
