"""Rules and levels for the LilyGO gesture maze."""
from dataclasses import dataclass
from collections import Counter
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass(frozen=True)
class Level:
    name: str
    landmark: str
    tiles: tuple[str, ...]
    patrol: tuple[tuple[int, int], ...] = ()

    def position(self, tile):
        for y, row in enumerate(self.tiles):
            if tile in row:
                return row.index(tile), y
        raise ValueError(f'{self.name} has no {tile} tile')


LEVELS = (
    Level('Pafos', 'Harbour Castle & mosaics', (
        '#######',
        '#S...##',
        '####.##',
        '#..K..#',
        '#.#####',
        '#E....#',
        '#######',
    )),
    Level('Limasol', 'Molos promenade & marina', (
        '########',
        '#S...#K#',
        '#.##.#.#',
        '#....#.#',
        '###....#',
        '#...##.#',
        '#E.....#',
        '########',
    )),
    Level('Nicosia', 'Venetian walls & Famagusta Gate', (
        '#########',
        '#S..#...#',
        '#.#.#.#K#',
        '#.#...#.#',
        '#.###.#.#',
        '#...#...#',
        '###.#.###',
        '#E......#',
        '#########',
    ), ((4, 7), (5, 7), (6, 7), (7, 7), (6, 7), (5, 7))),
)

# East, south, west, north, in clockwise order.
DIRECTIONS = ((1, 0), (0, 1), (-1, 0), (0, -1))
DIRECTION_NAMES = ('Right', 'Down', 'Left', 'Up')
PATROL_STEP_MS = 1450
PATROL_TRAVEL_MS = 360
SAVE_VERSION = 1
HISTORY_LIMIT = 256


class GestureGate:
    """Accept one motion after the player's hand returns to rest."""

    def __init__(self):
        self.armed = False

    def reset(self):
        self.armed = False

    def feed(self, label):
        if label == 'rest':
            self.armed = True
        elif label in ('rotation', 'rotation_left', 'rotation_right', 'translation') and self.armed:
            self.reset()
            return label
        return None


class Maze:
    def __init__(self):
        self.move_history = ()
        self.restart()

    def restart(self):
        self.index = 0
        self.reset()

    @property
    def level(self):
        return LEVELS[self.index]

    @property
    def final_level(self):
        return self.index == len(LEVELS) - 1

    def reset(self):
        self.ball = self.level.position('S')
        self.key = self.level.position('K')
        self.exit = self.level.position('E')
        self.heading = 0
        self.has_key = False
        self.cleared = False
        self.actions = 0
        self.patrol_ms = 0.
        self.patrol_target = None
        self.forecast_tile = None
        self.chase_cooldown = 0
        self.previous_direction = None

    def step_from_ball(self, direction):
        dx, dy = DIRECTIONS[direction]
        x, y = self.ball[0] + dx, self.ball[1] + dy
        rows = self.level.tiles
        if 0 <= y < len(rows) and 0 <= x < len(rows[y]) and rows[y][x] != '#':
            return x, y
        return None

    def predict_next_tile(self):
        """Estimate P(next direction | previous direction) from successful moves."""
        if self.previous_direction is None:
            return None
        counts = Counter(after for before, after in self.move_history if before == self.previous_direction)
        candidates = []
        for direction, count in counts.items():
            target = self.step_from_ball(direction)
            if target is not None and (target != self.exit or self.has_key):
                candidates.append((count, direction == self.heading, direction, target))
        if not candidates:
            return None
        count, _, _, target = max(candidates)
        return target if count >= 2 else None

    def choose_patrol_target(self, phase):
        route = self.level.patrol
        forward, backward = (phase + 1) % len(route), (phase - 1) % len(route)
        self.forecast_tile = None
        if self.chase_cooldown:
            self.chase_cooldown -= 1
            return forward
        forecast = self.predict_next_tile()
        if forecast not in route:
            return forward
        self.forecast_tile = forecast
        if abs(route[backward][0] - forecast[0]) < abs(route[forward][0] - forecast[0]):
            # Resume the patrol after one change of direction so it cannot camp on a tile.
            self.chase_cooldown = 2
            return backward
        return forward

    @property
    def patrol_tile(self):
        route = self.level.patrol
        return route[int(self.patrol_ms // PATROL_STEP_MS)] if route else None

    @property
    def patrol_position(self):
        route = self.level.patrol
        if not route:
            return None
        phase = int(self.patrol_ms // PATROL_STEP_MS)
        target = self.patrol_target if self.patrol_target is not None else (phase + 1) % len(route)
        a, b = route[phase], route[target]
        travel = max(0., (self.patrol_ms % PATROL_STEP_MS - (PATROL_STEP_MS - PATROL_TRAVEL_MS))
                     / PATROL_TRAVEL_MS)
        return tuple(start + (end - start) * travel for start, end in zip(a, b))

    def tick(self, elapsed_ms):
        if not self.level.patrol or self.cleared or elapsed_ms <= 0:
            return False
        caught = False
        while elapsed_ms > 0:
            phase = int(self.patrol_ms // PATROL_STEP_MS)
            progress = self.patrol_ms % PATROL_STEP_MS
            if self.patrol_target is None and progress + elapsed_ms >= PATROL_STEP_MS - PATROL_TRAVEL_MS:
                self.patrol_target = self.choose_patrol_target(phase)
            if progress + elapsed_ms < PATROL_STEP_MS:
                self.patrol_ms += elapsed_ms
                break
            elapsed_ms -= PATROL_STEP_MS - progress
            self.patrol_ms = self.patrol_target * PATROL_STEP_MS
            self.patrol_target = None
            self.forecast_tile = None
            if self.ball == self.patrol_tile:
                self.ball = self.level.position('S')
                self.heading = 0
                self.previous_direction = None
                caught = True
        return caught

    def next_level(self):
        if not self.cleared or self.final_level:
            return False
        self.index += 1
        self.reset()
        return True

    def apply(self, action):
        if self.cleared:
            return 'Level complete.'
        if action in ('rotation', 'rotation_left', 'rotation_right'):
            step = -1 if action == 'rotation_left' else 1
            self.heading = (self.heading + step) % len(DIRECTIONS)
            self.actions += 1
            return f'Heading {DIRECTION_NAMES[self.heading].lower()}.'
        if action != 'translation':
            raise ValueError(f'Unsupported action: {action}')
        target = self.step_from_ball(self.heading)
        if target is None:
            return 'A wall blocks that direction.'
        if target == self.exit and not self.has_key:
            return 'Collect the key to open the exit.'
        if target == self.patrol_tile:
            return 'The lantern blocks this tile. Wait for an opening.'

        self.ball = target
        if self.previous_direction is not None:
            pair = self.previous_direction, self.heading
            self.move_history = (*self.move_history[-(HISTORY_LIMIT-1):], pair)
        self.previous_direction = self.heading
        self.actions += 1
        if self.ball == self.key and not self.has_key:
            self.has_key = True
            return 'Key collected. The exit is open.'
        if self.ball == self.exit:
            self.cleared = True
            return 'Maze complete!' if self.final_level else 'Level complete. Advance to continue.'
        return f'Moved {DIRECTION_NAMES[self.heading].lower()}.'

    def snapshot(self):
        return {'version': SAVE_VERSION, 'level': self.index, 'ball': list(self.ball),
                'heading': self.heading, 'has_key': self.has_key, 'cleared': self.cleared,
                'actions': self.actions, 'patrol_ms': int(self.patrol_ms), 'patrol_target': self.patrol_target,
                'chase_cooldown': self.chase_cooldown, 'previous_direction': self.previous_direction,
                'move_history': [list(pair) for pair in self.move_history]}

    @classmethod
    def restore(cls, saved):
        if not isinstance(saved, dict) or saved.get('version') != SAVE_VERSION:
            raise ValueError('The save has an unsupported format.')
        game = cls()
        game.index = saved.get('level')
        if type(game.index) is not int or not 0 <= game.index < len(LEVELS):
            raise ValueError('The saved city does not exist.')
        game.reset()
        position = saved.get('ball')
        if not isinstance(position, list) or len(position) != 2 or any(type(n) is not int for n in position):
            raise ValueError('The saved position is invalid.')
        x, y = position
        rows = game.level.tiles
        if not 0 <= y < len(rows) or not 0 <= x < len(rows[y]) or rows[y][x] == '#':
            raise ValueError('The saved position is outside the route.')
        game.ball = x, y
        game.heading = saved.get('heading')
        game.actions = saved.get('actions')
        game.has_key = saved.get('has_key')
        game.cleared = saved.get('cleared')
        if (type(game.heading) is not int or not 0 <= game.heading < len(DIRECTIONS)
                or type(game.actions) is not int or game.actions < 0
                or type(game.has_key) is not bool or type(game.cleared) is not bool):
            raise ValueError('The saved game state is invalid.')
        if (game.ball == game.exit and not game.has_key) or game.cleared != (game.ball == game.exit):
            raise ValueError('The saved exit state is invalid.')
        patrol_ms = saved.get('patrol_ms', 0)
        if type(patrol_ms) is not int or patrol_ms < 0:
            raise ValueError('The saved patrol time is invalid.')
        cycle = len(game.level.patrol) * PATROL_STEP_MS
        game.patrol_ms = patrol_ms % cycle if cycle else 0
        history = saved.get('move_history', [])
        if (not isinstance(history, list) or len(history) > HISTORY_LIMIT
                or any(not isinstance(pair, list) or len(pair) != 2
                       or any(type(direction) is not int or direction not in range(len(DIRECTIONS))
                              for direction in pair) for pair in history)):
            raise ValueError('The saved movement history is invalid.')
        game.move_history = tuple(map(tuple, history))
        previous = saved.get('previous_direction')
        if previous is not None and (type(previous) is not int or previous not in range(len(DIRECTIONS))):
            raise ValueError('The saved previous movement is invalid.')
        game.previous_direction = previous
        cooldown = saved.get('chase_cooldown', 0)
        if type(cooldown) is not int or not 0 <= cooldown <= 2:
            raise ValueError('The saved chase cooldown is invalid.')
        game.chase_cooldown = cooldown
        target = saved.get('patrol_target')
        if target is not None:
            route = game.level.patrol
            phase = int(game.patrol_ms // PATROL_STEP_MS)
            if (type(target) is not int or not route
                    or target not in ((phase + 1) % len(route), (phase - 1) % len(route))):
                raise ValueError('The saved lantern target is invalid.')
            game.patrol_target = target
        return game


def save_game(path: Path, maze: Maze):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                prefix='.orbit-save-', suffix='.tmp', delete=False) as file:
            temporary = Path(file.name)
            json.dump(maze.snapshot(), file, indent=2)
            file.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_game(path: Path):
    try:
        with path.open(encoding='utf-8') as file:
            return Maze.restore(json.load(file))
    except FileNotFoundError:
        return None
