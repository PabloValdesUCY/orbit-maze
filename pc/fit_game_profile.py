"""Tune game gesture thresholds on practice trials and verify a held-out set."""
import argparse
from dataclasses import asdict
from itertools import product
import json
import os
from pathlib import Path
from statistics import median
from tempfile import NamedTemporaryFile

from calibrate_game import GESTURES
from capture import parse_data
from game_input import GameInput, MotionProfile, PROFILE_PATH, load_profile
from maze import parse_result
from maze_logic import GestureGate


def load_trials(directory):
    manifest = json.loads((directory / 'session.json').read_text(encoding='utf-8'))
    if manifest['status'] != 'complete':
        raise ValueError('Finish all 15 trials before fitting.')
    trials = []
    for item in manifest['trials']:
        name = item['file']
        if Path(name).name != name or item['expected'] not in GESTURES:
            raise ValueError('Invalid entry in the calibration manifest.')
        frames = []
        for line in (directory / name).read_text(encoding='utf-8').splitlines():
            row = parse_data(line)
            if row is not None:
                frames.append((row, None))
            else:
                result = parse_result(line)
                if result:
                    frames.append((None, result))
        trials.append((item, frames))
    return trials


def evaluate(factory, trials):
    outcomes = []
    for item, frames in trials:
        motion, gate = factory(), GestureGate()
        actions = []
        for row, prediction in frames:
            if prediction is not None:
                motion.observe_prediction(*prediction)
                continue
            burst = motion.burst
            event = motion.feed(row)
            if event in ('unclear', 'menu'):
                gate.reset()
            action = event if event == 'menu' else gate.feed(event)
            if action:
                actions.append({'gesture': action, 'after_go_ms': row[0]-item['go_ms'],
                                'decision_ms': row[0]-burst.start if burst else None})
        correct = len(actions) == 1 and actions[0]['gesture'] == item['expected'] and actions[0]['after_go_ms'] >= 0
        outcomes.append({'file': item['file'], 'expected': item['expected'], 'actions': actions, 'correct': correct})
    return outcomes


def summary(outcomes):
    correct = sum(item['correct'] for item in outcomes)
    missed = sum(not item['actions'] for item in outcomes)
    return {'total': len(outcomes), 'correct': correct, 'missed': missed, 'incorrect': len(outcomes)-correct-missed}


def decision_times(outcomes):
    values = [item['actions'][0]['decision_ms'] for item in outcomes if item['correct']]
    values = [value for value in values if value is not None]
    return {'median_ms': median(values) if values else None, 'max_ms': max(values) if values else None}


def install(profile_record):
    path = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=PROFILE_PATH.parent,
                                prefix='.gesture-profile-', suffix='.tmp', delete=False) as file:
            path = Path(file.name)
            json.dump(profile_record, file, indent=2)
            file.write('\n')
        os.replace(path, PROFILE_PATH)
    finally:
        if path:
            path.unlink(missing_ok=True)


def fit(directory, apply=False):
    trials = load_trials(directory)
    calibration = [(item, frames) for item, frames in trials if item['partition'] == 'calibration']
    validation = [(item, frames) for item, frames in trials if item['partition'] == 'validation']
    if (len(calibration), len(validation)) != (9, 6):
        raise ValueError('Nine calibration and six separate validation trials are required.')

    baseline = load_profile()
    profiles = {baseline, MotionProfile(), *(MotionProfile(*values) for values in product(
        (140, 155, 180, 210), (1.8, 2.4, 3.0), (70., 105., 145.), (.0036, .0048, .0055), (1, -1)
    ))}

    def rank(profile):
        outcomes = evaluate(lambda: GameInput(profile), calibration)
        scores, timing = summary(outcomes), decision_times(outcomes)
        change = (abs(profile.turn_degrees-baseline.turn_degrees)
                  + abs(profile.turn_per_g-baseline.turn_per_g)/60
                  + abs(profile.slide_rms_g-baseline.slide_rms_g)*400
                  + (1 if profile.yaw_sign != baseline.yaw_sign else 0))
        return (scores['correct'], -scores['incorrect'], -(timing['median_ms'] or 0), -(timing['max_ms'] or 0),
                -change, -abs(profile.decision_ms-baseline.decision_ms))

    selected = max(sorted(profiles, key=lambda profile: tuple(asdict(profile).values())), key=rank)
    calibration_result = evaluate(lambda: GameInput(selected), calibration)
    validation_result = evaluate(lambda: GameInput(selected), validation)
    baseline_result = evaluate(lambda: GameInput(baseline), validation)
    validation_scores = summary(validation_result)
    baseline_scores = summary(baseline_result)
    eligible = (validation_scores['correct'] >= max(5, baseline_scores['correct'])
                and validation_scores['incorrect'] == 0)
    record = {'source': directory.name, 'profile': asdict(selected),
              'calibration': summary(calibration_result), 'validation': validation_scores,
              'validation_decision_time': decision_times(validation_result),
              'baseline_validation': baseline_scores, 'baseline_decision_time': decision_times(baseline_result),
              'validation_trials': validation_result, 'eligible_to_install': eligible}
    (directory / 'profile_evaluation.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record, indent=2))
    if apply and eligible:
        install(record)
        print(f'Profile installed: {PROFILE_PATH}')
    elif apply:
        print('Kept the current profile. The candidate did not meet the accuracy criteria on the six validation trials.')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path, help='Directory containing a complete game calibration session')
    parser.add_argument('--apply', action='store_true', help='Install the profile if it passes validation')
    args = parser.parse_args()
    try:
        fit(args.session, args.apply)
    except (OSError, ValueError) as error:
        raise SystemExit(f'Cannot fit the game profile: {error}')
