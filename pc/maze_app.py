"""Desktop interface and input routing for Orbit Maze."""
from math import cos, pi, sin
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event, Thread
import time
import tkinter as tk

from maze_art import (ACCENT, DISPLAY, GOLD, HEIGHT, INK, LINE, MUTED,
                      PALETTES, PAPER, RED, WHITE, WIDTH, Scene, city_art,
                      diamond, gesture_icon, island_route)
from maze_logic import DIRECTION_NAMES, LEVELS, GestureGate, Maze, load_game, save_game

SAVE_PATH = Path(__file__).resolve().parents[1] / 'data' / 'orbit_save.json'
GESTURE_NAMES = {'rotation_left': 'Left turn', 'rotation_right': 'Right turn',
                 'rotation': 'Right turn', 'translation': 'Slide'}
NIGHT = '#153740'
SHADE = '#e8dfd1'


class OrbitMazeApp:
    def __init__(self, root, reader=None, save_path=SAVE_PATH):
        self.root = root
        self.save_path = save_path
        self.messages = SimpleQueue()
        self.stop = Event()
        self.reader = None
        self.gate = GestureGate()
        self.screen = 'menu'
        self.notice = ''
        self.saved_city = None
        try:
            loaded = load_game(save_path)
        except (ValueError, OSError):
            loaded = None
            self.notice = 'The saved journey could not be read. You can start a new route.'
        if loaded:
            self.saved_city = loaded.level.name
        self.maze = loaded or Maze()
        self.started = loaded is not None
        self.dirty = False
        self.exit_pending = False
        self.tutorial = False
        self.tutorial_seen = bool(loaded and (loaded.index > 0 or loaded.actions > 0))
        self.port_state = 'searching' if reader else 'keyboard'
        self.port = None
        self.model_id = None
        self.last_frame = time.monotonic()
        self.last_serial = None
        self.last_gesture = ''
        self.tracking = False
        self.paint_pending = True
        self.layout_key = None
        self.board_box = None
        self.motion = None
        self.turn = None
        self.clicks = []
        self.hover_targets = {}
        self.hovered = None
        self.fields = {}

        root.title('Orbit Maze - Cyprus Route')
        root.configure(bg=PAPER)
        root.geometry('1152x752')
        root.minsize(840, 560)
        root.protocol('WM_DELETE_WINDOW', self.exit_game)
        self.canvas = tk.Canvas(root, bg=PAPER, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.scene = Scene(self.canvas)
        self.canvas.bind('<Configure>', lambda _event: self.invalidate())
        self.canvas.bind('<Button-1>', self.click)
        self.canvas.bind('<Motion>', self.hover)
        self.canvas.bind('<Leave>', lambda _event: self.set_hover(None))
        root.bind('<Escape>', lambda _event: self.toggle_menu())
        root.bind('<Return>', lambda _event: self.keyboard_action('translation'))
        root.bind('<Control-s>', lambda _event: self.save())
        for key, action in (('q', 'rotation_left'), ('r', 'rotation_right'), ('f', 'translation')):
            root.bind(f'<KeyPress-{key}>', lambda _event, name=action: self.keyboard_action(name))
        if reader is not None:
            self.reader = Thread(target=reader, args=(self.messages, self.stop), daemon=True)
            self.reader.start()
        root.after(25, self.frame)

    def invalidate(self):
        self.paint_pending = True

    def hit_position(self, event):
        x, y = self.scene.logical(event.x, event.y)
        for x0, y0, x1, y1, callback in reversed(self.clicks):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return callback
        return None

    def click(self, event):
        callback = self.hit_position(event)
        if callback:
            callback()
        self.canvas.focus_set()

    def hover(self, event):
        self.set_hover(self.hit_position(event))

    def set_hover(self, callback):
        if self.hovered == callback:
            return
        for target, active in ((self.hovered, False), (callback, True)):
            if target in self.hover_targets:
                item, base, over = self.hover_targets[target]
                self.canvas.itemconfigure(item, fill=over if active else base)
        self.hovered = callback
        self.canvas.configure(cursor='hand2' if callback else '')

    def keyboard_action(self, action):
        # Keyboard moves apply immediately. The board uses the separate rest gate.
        self.action(action)

    def physical_action(self, gesture):
        if gesture == 'unclear':
            self.gate.reset()
            self.last_gesture = 'Unclear gesture'
            self.notice = 'Gesture unclear. Hold still, then make one clear slide or turn.'
            self.invalidate()
            return
        if gesture == 'menu':
            self.last_gesture = 'Tilt'
            self.gate.reset()
            if self.screen == 'play':
                self.open_menu()
            self.invalidate()
            return
        armed_before = self.gate.armed
        command = self.gate.feed(gesture)
        if command:
            self.action(command)
        elif armed_before != self.gate.armed or gesture != 'rest':
            self.invalidate()

    def start(self):
        if self.maze.cleared and self.maze.final_level:
            self.maze = Maze()
            self.motion = self.turn = None
            self.tutorial_seen = False
            self.dirty = True
        self.started = True
        self.screen = 'play'
        self.exit_pending = False
        self.tutorial = self.maze.index == 0 and not self.tutorial_seen
        self.notice = 'Find the key, then head for the exit.'
        self.gate.reset()
        self.invalidate()

    def open_menu(self):
        self.screen = 'menu'
        self.tutorial = False
        self.exit_pending = False
        self.notice = ''
        self.gate.reset()
        self.invalidate()

    def toggle_menu(self):
        if self.screen == 'play':
            self.open_menu()
        else:
            self.start()

    def save(self):
        try:
            save_game(self.save_path, self.maze)
        except OSError as error:
            self.notice = f'Could not save the journey: {error.strerror or type(error).__name__}.'
        else:
            self.started = True
            self.saved_city = self.maze.level.name
            self.dirty = False
            self.exit_pending = False
            self.notice = f'Progress saved in {self.saved_city}.'
        self.invalidate()

    def exit_game(self):
        if self.dirty:
            if self.screen != 'menu':
                self.open_menu()
            if not self.exit_pending:
                self.exit_pending = True
                self.notice = 'Unsaved progress. Save now or choose Exit again to leave.'
                self.invalidate()
                return
        self.close()

    def dismiss_tutorial(self):
        self.tutorial = False
        self.tutorial_seen = True
        self.gate.reset()
        self.invalidate()

    def next_city(self):
        if self.maze.next_level():
            self.motion = self.turn = None
            self.notice = ('Watch the lantern on the marked tiles.' if self.maze.level.patrol
                           else 'Take the waterfront route and collect the key.')
            self.gate.reset()
            self.dirty = True
            self.invalidate()
        elif self.maze.cleared and self.maze.final_level:
            self.open_menu()

    def action(self, gesture):
        self.last_gesture = GESTURE_NAMES.get(gesture, gesture)
        self.invalidate()
        if self.screen == 'menu':
            command = {'translation': self.start, 'rotation_right': self.save,
                       'rotation_left': self.exit_game}.get(gesture)
            if command:
                command()
            return
        if self.tutorial:
            if gesture == 'translation':
                self.dismiss_tutorial()
            return
        if self.maze.cleared:
            if gesture == 'translation':
                self.next_city()
            return
        now = time.monotonic()
        ball, count, heading = self.maze.ball, self.maze.actions, self.maze.heading
        angle = self.arrow_angle(now)
        self.notice = self.maze.apply(gesture)
        if self.maze.ball != ball:
            self.motion = (self.ball_position(now, ball), self.maze.ball, now)
        if self.maze.heading != heading:
            step = -1 if gesture == 'rotation_left' else 1
            previous = heading * pi/2
            # Keep the animated angle on the same revolution as the previous heading.
            previous = angle + (previous-angle+pi) % (2*pi)-pi
            self.turn = (angle, previous+step*pi/2, now)
        self.dirty = self.dirty or self.maze.actions != count

    def poll(self, now):
        for _ in range(128):
            try:
                kind, value = self.messages.get_nowait()
            except Empty:
                break
            if kind == 'connected':
                self.port, self.model_id = value
                self.port_state = 'connected'
                self.last_serial = now
                self.tracking = False
                self.gate.reset()
                self.invalidate()
            elif kind == 'gesture':
                self.last_serial = now
                self.physical_action(value)
                if self.stop.is_set():
                    return
            elif kind == 'activity':
                self.tracking = value
                self.invalidate()
            elif kind == 'heartbeat':
                self.last_serial = now
                if self.port_state == 'paused':
                    self.port_state = 'connected'
                    self.invalidate()
            elif kind == 'interrupted':
                self.gate.reset()
                self.tracking = False
                self.last_gesture = ''
                self.invalidate()
            elif kind in ('searching', 'unavailable'):
                self.port_state = kind
                self.gate.reset()
                self.tracking = False
                self.last_gesture = ''
                if value and self.screen == 'menu':
                    self.notice = value
                self.invalidate()
        if self.port_state == 'connected' and self.last_serial is not None and now-self.last_serial > 4:
            self.port_state = 'paused'
            self.gate.reset()
            self.tracking = False
            self.invalidate()

    def frame(self):
        now = time.monotonic()
        elapsed = min(140, (now-self.last_frame)*1000)
        self.last_frame = now
        self.poll(now)
        if self.stop.is_set():
            return
        active = self.screen == 'play' and not self.tutorial and not self.maze.cleared
        if active and self.maze.tick(elapsed):
            self.motion = self.turn = None
            self.dirty = True
            self.notice = 'The lantern sent you back to the entrance. Your key is safe.'
            self.invalidate()
        if self.paint_pending:
            self.draw(now)
        elif self.screen == 'play' and (self.motion or self.turn or (active and self.maze.level.patrol)):
            self.draw_actors(now)
        self.root.after(16, self.frame)

    def close(self):
        self.stop.set()
        if self.reader:
            self.reader.join(timeout=.25)
        self.root.destroy()

    def button(self, x, y, w, h, label, callback, *, dark=False):
        s = self.scene
        base, over = (ACCENT, '#125747') if dark else ('#e9ede3', '#dce6d7')
        surface = s.round(x,y,w,h,9,base)
        s.text(x+w/2,y+h/2,label,15,color=WHITE if dark else INK,align='center',weight='bold')
        self.clicks.append((x,y,x+w,y+h,callback))
        self.hover_targets[callback] = surface, base, over

    def device_label(self):
        if self.port_state == 'connected':
            if self.tracking:
                return f'{self.port}  •  Reading gesture', ACCENT
            if self.gate.armed:
                return f'{self.port}  •  Ready', ACCENT
            return f'{self.port}  •  Hold still', GOLD
        if self.port_state == 'keyboard':
            return 'Keyboard mode', MUTED
        if self.port_state == 'paused':
            return 'Waiting for IMU data', GOLD
        return 'Connect LilyGO via USB', GOLD

    def draw(self, now=None):
        now = time.monotonic() if now is None else now
        self.paint_pending = False
        layout = (self.screen, self.maze.index, self.tutorial, self.maze.cleared,
                  self.canvas.winfo_width(), self.canvas.winfo_height())
        if self.layout_key != layout:
            self.layout_key = layout
            self.draw_layout()
        self.refresh_hud()
        self.draw_actors(now)

    def draw_layout(self):
        s = self.scene
        s.resize()
        s.tag = 'scene'
        self.canvas.delete('all')
        self.clicks.clear()
        self.hover_targets.clear()
        self.fields.clear()
        self.set_hover(None)
        self.board_box = None
        s.rect(0,0,WIDTH,HEIGHT,PAPER)
        s.round(34,17,42,42,12,NIGHT)
        s.oval(42,25,26,26,'','#749c9c')
        diamond(s,55,38,10,'#f3cb8b')
        diamond(s,55,38,3,NIGHT)
        s.text(88,38,'Orbit Maze',22,align='w',face=DISPLAY,weight='bold')
        s.line((34,74,1086,74),LINE)
        s.round(833,18,253,40,20,'#e9e7db')
        self.fields['device_dot'] = s.oval(851,33,10,10,GOLD)
        self.fields['device'] = s.text(872,38,'',14,align='w',weight='bold')
        if self.screen == 'menu':
            self.draw_menu()
        else:
            self.draw_play()

    def refresh_hud(self):
        c, fields = self.canvas, self.fields
        status, colour = self.device_label()
        c.itemconfigure(fields['device'], text=status, fill=colour)
        c.itemconfigure(fields['device_dot'], fill=colour)
        if self.screen == 'menu':
            saved = (f'Saved in {self.saved_city}' if self.saved_city else
                     f'Current stop: {self.maze.level.name}' if self.started else 'Start in Pafos')
            if self.dirty:
                saved += '  •  Unsaved progress'
            start = ('Start again' if self.maze.cleared and self.maze.final_level else
                     'Continue game' if self.started else 'Start game')
            c.itemconfigure(fields['save_state'], text=saved)
            c.itemconfigure(fields['start'], text=start)
            c.itemconfigure(fields['exit'], text='Confirm exit' if self.exit_pending else 'Exit game')
        else:
            game = self.maze
            c.itemconfigure(fields['objective'], text='Reach the exit' if game.has_key else 'Find the key')
            c.itemconfigure(fields['moves'], text=f'{game.actions} moves  /  {DIRECTION_NAMES[game.heading]}')
            c.itemconfigure('key', state='hidden' if game.has_key else 'normal')
            c.itemconfigure(fields['exit_tile'], fill='#cce6c0' if game.has_key else '#ede4cf')
            c.itemconfigure(fields['exit_label'], fill=ACCENT if game.has_key else MUTED)
        notice = self.notice or ('Hold still until Ready appears.' if self.port_state == 'connected'
                                 else 'Use Q, R and F or connect the LilyGO.')
        c.itemconfigure(fields['notice'], text=notice, fill=RED if self.exit_pending else INK)
        c.itemconfigure(fields['input'], text=f'Last input: {self.last_gesture}' if self.last_gesture else '')

    def draw_menu(self):
        s = self.scene
        s.round(34,101,655,327,21,SHADE)
        s.round(34,95,655,327,21,NIGHT)
        s.round(282,114,387,288,15,'#1c4650')
        island_route(s,296,147,360,220)
        s.line((60,152,88,152),'#e8b972',2)
        s.text(98,152,'CYPRUS ROUTE',12,color='#fcdfa2',align='w',weight='bold')
        s.text(57,179,'Across\nCyprus',49,color=WHITE,face=DISPLAY,weight='bold')
        s.text(60,310,'Guide the ball through three cities. Collect a key at each stop.',16,
               color='#d4e6e1',wrap=200)
        s.text(34,450,'The route',26,face=DISPLAY,weight='bold')
        for index, (level, caption) in enumerate(zip(LEVELS, (
            'Harbour Castle and mosaics', 'Molos promenade and marina', 'Venetian walls and city gate'
        ))):
            x = 34+222*index
            p = PALETTES[index]
            s.round(x,493,211,186,14,SHADE)
            s.round(x,489,211,186,14,WHITE)
            city_art(s,index,x+9,498,193,109)
            s.round(x+16,505,28,26,7,NIGHT)
            s.text(x+30,518,str(index+1),13,color=WHITE,align='center',weight='bold')
            s.text(x+14,617,level.name,24,color=p.token,face=DISPLAY,weight='bold')
            s.text(x+15,649,caption,12,color=MUTED)

        s.round(714,101,372,578,20,SHADE)
        s.round(714,95,372,580,20,WHITE)
        s.text(739,119,'Your journey',30,face=DISPLAY,weight='bold')
        self.fields['save_state'] = s.text(740,163,'',14,color=MUTED)
        for i, (field, title, hint, shortcut, glyph, callback) in enumerate((
            ('start', '', 'Slide sideways', 'F', 'translation', self.start),
            ('save', 'Save game', 'Turn right', 'R', 'rotation_right', self.save),
            ('exit', '', 'Turn left', 'Q', 'rotation_left', self.exit_game),
        )):
            y = 203+94*i
            primary = i == 0
            fg = WHITE if primary else INK
            base, over = (ACCENT, '#125747') if primary else ('#f0efe7', '#e2ebe1')
            surface = s.round(739,y,322,78,13,base)
            s.round(753,y+16,46,46,12,'#297b69' if primary else '#e2e9dc')
            gesture_icon(s,glyph,762,y+25,28,fg if primary else ACCENT)
            self.fields[field] = s.text(813,y+15,title,20,color=fg,weight='bold')
            s.text(814,y+45,hint,14,color='#e2f2ee' if primary else MUTED)
            s.round(1018,y+24,29,29,7,'#297b69' if primary else WHITE)
            s.text(1032.5,y+38.5,shortcut,15,color=fg,align='center',weight='bold')
            self.clicks.append((739,y,1061,y+78,callback))
            self.hover_targets[callback] = surface, base, over
        self.draw_feedback(739,503,322,146)

    def draw_play(self):
        s, game = self.scene, self.maze
        p = PALETTES[game.index]
        s.text(34,77,game.level.name,43,face=DISPLAY,weight='bold')
        for index, level in enumerate(LEVELS):
            x = 714+126*index
            current = index == game.index
            s.round(x,89,120,31,15,p.token if current else '#eae6db')
            s.text(x+60,104,level.name,13,color=WHITE if current else MUTED,
                   align='center',weight='bold' if current else 'normal')
        s.round(34,137,662,551,19,SHADE)
        s.round(34,132,662,552,19,NIGHT)
        s.round(51,147,181,32,16,'#2c555c')
        diamond(s,69,163,5,'#f6cc87')
        self.fields['objective'] = s.text(84,163,'',14,color=WHITE,align='w',weight='bold')
        self.fields['moves'] = s.text(676,163,'',14,color='#deebe7',align='e')
        self.draw_board()
        self.create_actors()

        s.round(714,137,372,551,19,SHADE)
        s.round(714,132,372,552,19,WHITE)
        city_art(s,game.index,729,147,342,148)
        s.text(732,309,game.level.landmark,20,color=p.token,face=DISPLAY,weight='bold')
        s.line((732,345,1069,345),LINE)
        for i,(kind,caption,key) in enumerate((
            ('translation','Slide sideways to move','F'),
            ('rotation_left','Turn to aim left or right','Q / R'),
            ('rest','Hold still between gestures',''),
            ('menu','Tilt up to open menu','Esc'),
        )):
            y=356+37*i
            s.round(732,y,32,32,8,'#edf0e7')
            gesture_icon(s,kind,738,y+6,21,p.token)
            s.text(777,y+16,caption,14,align='w')
            if key:
                s.text(1064,y+16,key,13,color=MUTED,align='e',weight='bold')
        self.draw_feedback(732,515,337,98)
        self.button(732,628,121,37,'Menu  /  Esc',self.open_menu)
        if game.level.patrol:
            s.oval(944,644,7,7,RED)
            s.text(1068,647,'Lantern patrol',13,color=RED,align='e',weight='bold')

        if self.tutorial:
            self.draw_guide()
        elif game.cleared:
            self.draw_cleared()

    def draw_feedback(self, x, y, w, h):
        s = self.scene
        s.round(x,y,w,h,12,'#f2f0e7')
        s.text(x+15,y+11,'STATUS',11,color=MUTED,weight='bold')
        self.fields['notice'] = s.text(x+15,y+31,'',14,wrap=w-30)
        self.fields['input'] = s.text(x+15,y+h-17,'',13,color=ACCENT,align='w',weight='bold')

    def draw_board(self):
        s, game=self.scene,self.maze
        p=PALETTES[game.index]
        rows=game.level.tiles
        size=min(612/len(rows[0]),469/len(rows))
        width,height=size*len(rows[0]),size*len(rows)
        x0,y0=365-width/2,425-height/2
        self.board_box=(x0,y0,size)
        s.round(x0-9,y0-9,width+18,height+18,11,p.trim)
        for row, tiles in enumerate(rows):
            for col, tile in enumerate(tiles):
                x,y=x0+size*col,y0+size*row
                wall=tile == '#'
                route=(col,row) in game.level.patrol
                color=p.wall if wall else '#efbd8c' if route else p.floors[(col+row)%2]
                s.rect(x+.5,y+.5,size-1,size-1,color)
                if wall and game.index == 0:
                    diamond(s,x+size/2,y+size/2,size*.19,'#c9825e')
                    diamond(s,x+size/2,y+size/2,size*.075,'#ebba83')
                elif wall and game.index == 1:
                    for d in (.38,.62):
                        s.line((x+size*.22,y+size*d,x+size*.43,y+size*(d-.05),
                                x+size*.78,y+size*d),'#519a97',1.5)
                elif wall:
                    s.line((x+size*.08,y+size*.52,x+size*.92,y+size*.52),'#a97760',1.4)
                    s.line((x+size*.43,y+size*.14,x+size*.43,y+size*.51),'#a97760',1.4)
                elif route:
                    diamond(s,x+size/2,y+size/2,size*.09,'#ba6451')

        x,y=self.cell(game.exit)
        self.fields['exit_tile'] = s.oval(x-size*.37,y-size*.37,size*.74,size*.74,'#ede4cf',p.trim,2)
        self.fields['exit_label'] = s.text(x,y,'EXIT',max(10,size*.24),align='center',weight='bold')
        s.tag = 'key'
        x,y=self.cell(game.key)
        s.oval(x-size*.31,y-size*.31,size*.62,size*.62,'#ffe5a0','#c98f41',1.2)
        s.oval(x-size*.19,y-size*.095,size*.19,size*.19,'',GOLD,2.5)
        s.line((x,y,x+size*.23,y,x+size*.23,y+size*.105),GOLD,2.5)
        s.line((x+size*.115,y,x+size*.115,y+size*.075),GOLD,2)
        s.tag = 'scene'

    def cell(self, position):
        x,y,size=self.board_box
        return x+size*(position[0]+.5),y+size*(position[1]+.5)

    def ball_position(self, now, fallback=None):
        if self.motion is None:
            return self.maze.ball if fallback is None else fallback
        old,new,started=self.motion
        fraction=min(1.,max(0.,(now-started)/.145))
        if fraction == 1.:
            self.motion = None
            return new
        eased=1-(1-fraction)**3
        return tuple(a+(b-a)*eased for a,b in zip(old,new))

    def arrow_angle(self, now):
        if self.turn is None:
            return self.maze.heading*pi/2
        start, target, started = self.turn
        progress = max(0, (now-started)/.13)
        if progress >= 1:
            self.turn = None
            return target
        return start+(target-start)*(1-(1-progress)**3)

    def create_actors(self):
        s, game = self.scene, self.maze
        size = self.board_box[2]
        self.ball_at = self.lantern_at = (0, 0)
        if game.level.patrol:
            s.tag = 'lantern'
            self.lantern_glow = s.oval(0,0,0,0,'#df9663')
            s.oval(-size*.24,-size*.24,size*.48,size*.48,'#8d4138')
            s.round(-size*.14,-size*.16,size*.28,size*.31,size*.04,'#ffe198')
            s.line((-size*.13,size*.18,size*.13,size*.18),'#4f2d29',2.6)
        s.tag = 'ball'
        s.oval(-size*.26,-size*.16,size*.52,size*.47,'#93876b')
        s.oval(-size*.25,-size*.25,size*.50,size*.50,PALETTES[game.index].token,'#f7f5dc',1.6)
        s.oval(-size*.15,-size*.15,size*.13,size*.105,'#f0ffea')
        s.tag = 'scene'
        self.arrow = s.poly((0,0,0,0,0,0),NIGHT,'#fff4d5')

    def draw_actors(self, now):
        if self.board_box is None:
            return
        s, c, game = self.scene, self.canvas, self.maze
        size = self.board_box[2]
        lantern = game.patrol_position
        if lantern is not None:
            lx, ly = self.cell(lantern)
            ox, oy = self.lantern_at
            if (lx, ly) != self.lantern_at:
                c.move('lantern', (lx-ox)*s.scale, (ly-oy)*s.scale)
                self.lantern_at = lx, ly
            radius = size*(.32+.03*sin(now*7.5))
            c.coords(self.lantern_glow, *s.points((lx-radius,ly-radius,lx+radius,ly+radius)))
        x, y = self.cell(self.ball_position(now))
        ox, oy = self.ball_at
        if (x, y) != self.ball_at:
            c.move('ball', (x-ox)*s.scale, (y-oy)*s.scale)
            self.ball_at = x, y
        angle = self.arrow_angle(now)
        dx,dy=cos(angle),sin(angle)
        px,py=-dy,dx
        tx,ty=x+dx*size*.47,y+dy*size*.47
        bx,by=x+dx*size*.27,y+dy*size*.27
        spread=size*.12
        c.coords(self.arrow, *s.points((tx,ty,bx+px*spread,by+py*spread,bx-px*spread,by-py*spread)))

    def draw_guide(self):
        s=self.scene
        s.round(81,176,571,439,24,NIGHT)
        s.round(88,182,557,421,18,WHITE)
        s.text(115,210,'PAFOS  /  TUTORIAL',14,color=GOLD,weight='bold')
        s.text(116,241,'Learn the controls',37,face=DISPLAY,weight='bold')
        s.text(117,295,'Keep the OLED facing up. Collect the key and reach the gate.',16,color=MUTED,wrap=493)
        for i,(kind,label,desc) in enumerate((
            ('rest','Hold still','Wait for Ready before the next action.'),
            ('rotation_left','Turn left or right','Rotate the arrow in that direction.'),
            ('translation','Slide sideways','Move one tile where the arrow points.'),
        )):
            y=347+i*53
            s.round(118,y,39,39,8,'#e8eee3')
            gesture_icon(s,kind,126,y+8,23,ACCENT)
            s.text(170,y+1,label,15,weight='bold')
            s.text(170,y+22,desc,14,color=MUTED)
        self.button(118,523,273,43,'Start playing  /  Slide or Enter',self.dismiss_tutorial,dark=True)

    def draw_cleared(self):
        s=self.scene
        final=self.maze.final_level
        s.round(102,232,524,261,23,NIGHT)
        s.round(109,238,510,244,17,WHITE)
        s.text(134,262,self.maze.level.name.upper(),14,color=GOLD,weight='bold')
        s.text(136,293,'Journey complete' if final else 'City cleared',37,face=DISPLAY,weight='bold')
        text=('You reached the last gate in Nicosia.' if final
              else f'Next stop: {LEVELS[self.maze.index+1].name}.')
        s.text(137,348,text,17,color=MUTED)
        self.button(136,394,249,44,'Back to menu  /  Slide' if final else 'Next city  /  Slide',
                    self.next_city,dark=True)
