"""Read recorded IMU sessions and build the same features as the firmware."""

import csv
import hashlib
import io
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

LABELS = ("rest", "rotation", "translation")
AXES = ("ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps")
COLUMNS = ("timestamp_ms", *AXES)
FEATURE_NAMES = tuple(f"{stat}_{axis}" for stat in ("mean", "std") for axis in AXES)
WINDOW_SIZE = 100
MAX_GAP_MS = 100
MIN_WINDOWS_PER_LABEL = 5
MIN_SESSIONS = 4


@dataclass
class FileQuality:
    rows: int = 0
    accepted_rows: int = 0
    malformed_rows: int = 0
    invalid_timestamps: int = 0
    nonincreasing_timestamps: int = 0
    invalid_measurements: int = 0
    gaps: int = 0
    windows_kept: int = 0
    windows_discarded: int = 0
    samples_in_discarded_windows: int = 0


@dataclass
class Session:
    name: str
    features: dict[str, list[np.ndarray]] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    metadata_sha256: str | None = None
    metadata_status: str | None = None


def window_features(samples: list[np.ndarray]) -> np.ndarray:
    """Accumulate float32 one sample at a time, in the order used on the ESP32."""
    sums = np.zeros(len(AXES), dtype=np.float32)
    sums_sq = np.zeros_like(sums)
    divisor = np.float32(WINDOW_SIZE)
    with np.errstate(over="ignore", invalid="ignore"):
        for sample in samples:
            sums += sample
            sums_sq += sample * sample
        means = sums / divisor
        variance = sums_sq / divisor - means * means
        stds = np.sqrt(np.maximum(np.float32(0), variance))
    return np.concatenate((means, stds))


def read_recording(path: Path) -> tuple[list[np.ndarray], FileQuality, str]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    quality = FileQuality()
    windows = []
    pending = []
    previous_ms = None

    def discard_pending() -> None:
        if pending:
            quality.windows_discarded += 1
            quality.samples_in_discarded_windows += len(pending)
            pending.clear()

    try:
        rows = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        if tuple(next(rows, ())) != COLUMNS:
            raise ValueError(f"expected header {','.join(COLUMNS)}")

        for row in rows:
            quality.rows += 1
            if len(row) != len(COLUMNS):
                quality.malformed_rows += 1
                discard_pending()
                continue

            try:
                timestamp_ms = int(row[0])
                if not 0 <= timestamp_ms <= 0xFFFFFFFF:
                    raise ValueError
            except ValueError:
                quality.invalid_timestamps += 1
                discard_pending()
                continue

            if previous_ms is not None:
                elapsed_ms = timestamp_ms - previous_ms
                if elapsed_ms <= 0:
                    quality.nonincreasing_timestamps += 1
                    discard_pending()
                    continue
                if elapsed_ms > MAX_GAP_MS:
                    quality.gaps += 1
                    discard_pending()
            previous_ms = timestamp_ms

            try:
                with np.errstate(over="ignore", invalid="ignore"):
                    sample = np.asarray(row[1:], dtype=np.float32)
                if not np.isfinite(sample).all():
                    raise ValueError
            except (ValueError, OverflowError):
                quality.invalid_measurements += 1
                discard_pending()
                continue

            quality.accepted_rows += 1
            pending.append(sample)
            if len(pending) == WINDOW_SIZE:
                features = window_features(pending)
                if np.isfinite(features).all():
                    windows.append(features)
                    quality.windows_kept += 1
                    pending.clear()
                else:
                    discard_pending()
        discard_pending()
    except (ValueError, csv.Error) as exc:
        raise ValueError(f"{path}: {exc}") from exc

    return windows, quality, digest


def read_sessions(raw_dir: Path) -> tuple[list[Session], list[dict]]:
    """Read all visible session directories and retain their quality evidence."""
    if not raw_dir.is_dir():
        raise ValueError(f"Recording directory does not exist: {raw_dir}")

    sessions = []
    files = []
    for directory in sorted(raw_dir.iterdir()):
        if not directory.is_dir() or directory.name.startswith("."):
            continue

        session = Session(directory.name)
        metadata_path = directory / "session.json"
        if metadata_path.is_file():
            metadata = metadata_path.read_bytes()
            session.metadata_sha256 = hashlib.sha256(metadata).hexdigest()
            try:
                record = json.loads(metadata)
                status = record.get("status") if isinstance(record, dict) else None
                if isinstance(status, str):
                    session.metadata_status = status
                if status != "complete":
                    session.issues.append("session.json does not mark this capture complete")
            except (ValueError, UnicodeError):
                session.issues.append("invalid session.json")
        for label in LABELS:
            path = directory / f"{label}.csv"
            if not path.is_file():
                session.issues.append(f"missing {path.name}")
                continue

            windows, quality, digest = read_recording(path)
            session.features[label] = windows
            files.append({
                "path": path.relative_to(raw_dir).as_posix(),
                "session": session.name,
                "label": label,
                "sha256": digest,
                **asdict(quality),
            })
            if len(windows) < MIN_WINDOWS_PER_LABEL:
                session.issues.append(
                    f"{label}: {len(windows)}/{MIN_WINDOWS_PER_LABEL} complete windows"
                )
        sessions.append(session)

    return sessions, files


def select_sessions(sessions: list[Session], test_name: str | None) -> tuple[list[Session], Session]:
    complete = [session for session in sessions if not session.issues]
    if len(complete) < MIN_SESSIONS:
        details = "; ".join(
            f"{session.name} ({', '.join(session.issues)})" for session in sessions if session.issues
        )
        error = f"Need {MIN_SESSIONS} complete sessions, found {len(complete)}."
        raise ValueError(f"{error} Incomplete: {details}" if details else error)

    if test_name is None:
        test = complete[-1]
    else:
        test = next((session for session in complete if session.name == test_name), None)
        if test is None:
            raise ValueError(f"Test session {test_name!r} is missing or incomplete.")
    return [session for session in complete if session is not test], test


def stack_sessions(sessions: list[Session]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    features, labels, groups = [], [], []
    for session in sessions:
        for index, label in enumerate(LABELS):
            windows = session.features[label]
            features.extend(windows)
            labels.extend([index] * len(windows))
            groups.extend([session.name] * len(windows))
    return np.asarray(features, dtype=np.float32), np.asarray(labels), np.asarray(groups)
