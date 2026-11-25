"""Canvas artwork for the three Cyprus cities and the island route."""
from dataclasses import dataclass
from math import cos, pi, sin

WIDTH, HEIGHT = 1120, 720
INK = '#182b2c'
PAPER = '#f7f3e9'
WHITE = '#fffdf7'
MUTED = '#526663'
LINE = '#e1e4d7'
ACCENT = '#176b59'
GOLD = '#ae631f'
BLUE = '#17424e'
RED = '#a34138'
FONT = 'Segoe UI'
DISPLAY = 'Georgia'


@dataclass(frozen=True)
class Palette:
    sky: str
    landscape: str
    detail: str
    wall: str
    floors: tuple[str, str]
    trim: str
    token: str


PALETTES = (
    Palette('#f8d1a1', '#6c9c9a', '#cf804d', '#a95d43', ('#ffe8ba', '#f7d79c'), '#a06a3c', '#166d70'),
    Palette('#bbdfdc', '#428b94', '#d88654', '#2c6f73', ('#def2df', '#cce7cc'), '#317979', '#1c5b86'),
    Palette('#edba93', '#a65c4f', '#c6885e', '#8c5a4a', ('#f3d0a7', '#f9dfbd'), '#996747', '#436646'),
)


class Scene:
    def __init__(self, canvas):
        self.canvas = canvas
        self.tag = 'scene'
        self.resize()

    def resize(self):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.scale = max(.1, min(w / WIDTH, h / HEIGHT))
        self.x = (w - WIDTH * self.scale) / 2
        self.y = (h - HEIGHT * self.scale) / 2

    def points(self, coords):
        return tuple(value * self.scale + (self.x if i % 2 == 0 else self.y) for i, value in enumerate(coords))

    def logical(self, x, y):
        return ((x - self.x) / self.scale, (y - self.y) / self.scale)

    def rect(self, x, y, w, h, fill, outline='', width=1):
        self.canvas.create_rectangle(*self.points((x, y, x+w, y+h)), fill=fill,
                                     outline=outline, width=max(1, width*self.scale), tags=self.tag)

    def round(self, x, y, w, h, r, fill):
        return self.canvas.create_polygon(*self.points(self.round_points(x,y,w,h,r)),
                                          smooth=True, splinesteps=9, fill=fill,
                                          outline='', tags=self.tag)

    @staticmethod
    def round_points(x, y, w, h, r):
        # Four soft corners on a single canvas item.
        a, b = x+w, y+h
        return (x+r,y, a-r,y, a,y, a,y+r, a,b-r, a,b, a-r,b,
                x+r,b, x,b, x,b-r, x,y+r, x,y)

    def oval(self, x, y, w, h, fill, outline='', width=1):
        return self.canvas.create_oval(*self.points((x, y, x+w, y+h)), fill=fill,
                                       outline=outline, width=max(1, width*self.scale), tags=self.tag)

    def line(self, coords, fill, width=1, dash=None):
        self.canvas.create_line(*self.points(coords), fill=fill, width=max(1, width*self.scale),
                                dash=dash, capstyle='round', joinstyle='round', tags=self.tag)

    def poly(self, coords, fill, outline=''):
        return self.canvas.create_polygon(*self.points(coords), fill=fill, outline=outline, tags=self.tag)

    def text(self, x, y, value, size=16, *, color=INK, align='nw', weight='normal',
             face=FONT, wrap=0, justify='left'):
        font = (face, -max(8, round(size*self.scale)), weight)
        return self.canvas.create_text(*self.points((x, y)), text=value, fill=color, anchor=align,
                                       font=font, width=round(wrap*self.scale), justify=justify, tags=self.tag)


def diamond(s, x, y, r, color):
    s.poly((x, y-r, x+r, y, x, y+r, x-r, y), color)


def city_art(s, index, x, y, w, h):
    """Draw an original postcard scene with features from the named city."""
    p = PALETTES[index]
    X = lambda u: x+u*w
    Y = lambda v: y+v*h

    def rect(a, b, c, d, color):
        s.rect(X(a), Y(b), c*w, d*h, color)

    def oval(a, b, c, d, color):
        s.oval(X(a), Y(b), c*w, d*h, color)

    def poly(*points, color):
        s.poly(tuple(v for a, b in points for v in (X(a), Y(b))), color)

    def line(*points, color, width=1):
        s.line(tuple(v for a, b in points for v in (X(a), Y(b))), color, width)

    rect(0, 0, 1, 1, p.sky)
    oval(.76, .105, .10, .18, '#fff1c2')
    poly((0,.64),(.16,.41),(.32,.58),(.52,.36),(.76,.60),(1,.45),(1,1),(0,1),
         color=('#d7a886', '#93b9ad', '#cb8f71')[index])
    rect(0, .65, 1, .35, p.landscape)
    if index == 0:
        for i in range(4):
            line((.03 + .13 * (i % 2), .76 + .06*i), (.73+.05*(i%2), .76+.06*i), color='#8fb7a9', width=2)
        # The square tower and the harbour causeway.
        rect(.16, .45, .48, .29, '#bb764c')
        rect(.34, .32, .23, .40, '#db9d64')
        rect(.39, .39, .18, .055, '#edb881')
        for j in range(5):
            rect(.345+j*.047, .28, .026, .07, '#db9d64')
        oval(.432, .52, .056, .16, '#75483d')
        rect(.432, .60, .056, .14, '#75483d')
        poly((.12,.72),(.73,.72),(.84,.80),(.06,.80), color='#e9b77d')
        for j in range(10):
            diamond(s, X(.10+j*.083), Y(.9), min(w*.019, h*.065),
                    ('#f4bd75','#eddfaa','#a97060')[j % 3])
    elif index == 1:
        for i in range(4):
            line((.39,.72+.052*i),(.94,.72+.052*i),color='#73adb0',width=2)
        rect(0,.72, .39,.28,'#ccb88d')
        rect(0,.714,.42,.047,'#e0d4aa')
        for a, height in ((.10,.42),(.23,.31),(.35,.43)):
            line((a,.75),(a+.022,height), color='#835746', width=4)
            for drift, top in ((-.078,.025),(-.06,-.095),(.018,-.123),(.087,-.018),(.076,.062)):
                line((a+.022,height),(a+drift*.65,height+top*.7-.03),(a+drift,height+top),
                     color='#3a6859', width=3)
        for a, b, size in ((.54,.78,1),(.78,.71,.66)):
            line((a,b-.36*size),(a,b),color='#414f50',width=2)
            poly((a+.008,b-.34*size),(a+.11*size,b-.035),(a+.008,b-.035),color='#fff3c8')
            poly((a-.058*size,b),(a+.12*size,b),(a+.088*size,b+.065),(a-.032*size,b+.065),color='#f0c098')
    else:
        rect(0,.73,1,.27,'#956150')
        rect(.12,.48,.74,.34,'#c78a66')
        poly((.12,.48),(.18,.43),(.79,.43),(.86,.48),color='#de9f71')
        for row in range(3):
            b=.53+row*.071
            line((.14,b),(.84,b),color='#ad755c')
            for j in range(6):
                a=.19+j*.107+(row%2)*.04
                if not .41<a<.59:
                    line((a,b),(a,b+.07),color='#ad755c')
        oval(.41,.55,.17,.25,'#844d44')
        rect(.41,.675,.17,.15,'#844d44')
        oval(.442,.60,.107,.17,'#493d40')
        rect(.442,.685,.107,.15,'#493d40')
        poly((.44,.83),(.55,.83),(.65,1),(.35,1),color='#d9a17c')
        for a in (.33,.67):
            line((a,.67),(a,.76),color='#654344',width=2)
            oval(a-.013,.64,.026,.055,'#ffdb85')


def island_route(s, x, y, w, h):
    """Stylised outline with the playable route, drawn at the menu's scale."""
    X = lambda t: x+t*w
    Y = lambda t: y+t*h
    for row in range(6):
        yy = Y(row / 5)
        s.line((x, yy, x+w, yy), '#34606b')
    for col in range(9):
        xx = X(col / 8)
        s.line((xx, y, xx, y+h), '#34606b')
    coast = ((.06,.54),(.105,.49),(.13,.39),(.20,.30),(.28,.30),(.36,.37),(.49,.36),
             (.58,.29),(.68,.30),(.73,.23),(.83,.19),(.91,.08),(.99,.03),(.97,.12),
             (.90,.24),(.83,.31),(.8,.42),(.78,.48),(.84,.61),(.78,.67),(.70,.60),
             (.65,.66),(.63,.74),(.57,.77),(.50,.86),(.49,.93),(.44,.87),(.35,.85),
             (.29,.76),(.23,.75),(.18,.70),(.11,.71),(.065,.65))
    outline = tuple(v for u, t in coast for v in (X(u), Y(t)))
    s.poly(outline, '#dcad74', '#ffe4ac')
    inner = (.12,.55,.22,.44,.31,.50,.42,.46,.54,.47,.66,.39,.72,.39)
    s.line(tuple(v for a,b in zip(inner[::2],inner[1::2]) for v in (X(a),Y(b))), '#bc8b58', 2)
    stops = ((.14,.65,'Pafos',-2,14),(.45,.80,'Limasol',-5,17),(.57,.51,'Nicosia',12,-20))
    s.line(tuple(v for a,b,*_ in stops for v in (X(a),Y(b))), '#15333b', 2, (3,4))
    for a,b,name,dx,dy in stops:
        s.oval(X(a)-6,Y(b)-6,12,12,'#fff7df','#163743',2)
        s.text(X(a)+dx,Y(b)+dy,name,12,color='#142e34' if name == 'Nicosia' else '#fff5df',
               weight='bold', align='n' if dx < 0 else 'nw')
    cx, cy = x+w-16, y+h-22
    for i in range(4):
        theta=i*pi/2
        s.line((cx,cy,cx+13*cos(theta),cy+13*sin(theta)), '#9fb7b4', 1.5)
    diamond(s,cx,cy,4,'#ffe3a0')
    s.text(cx,cy-20,'N',10,color='#eaf1e5',align='s',weight='bold')


def gesture_icon(s, kind, x, y, size, color):
    if kind == 'translation':
        s.line((x+size*.15,y+size*.5,x+size*.84,y+size*.5),color,2.2)
        for side in (-1, 1):
            end=x+size*(.15 if side<0 else .84)
            s.line((end-side*size*.19,y+size*.30,end,y+size*.5,end-side*size*.19,y+size*.70),color,2.2)
    elif kind == 'menu':
        s.poly((x+3,y+size*.73,x+size*.58,y+size*.22,x+size*.84,y+size*.47,x+size*.31,y+size*.92), '',color)
        s.line((x+size*.2,y+size*.47,x+size*.2,y+size*.14),color,2)
    elif kind == 'rest':
        s.line((x+size*.21,y+size*.49,x+size*.79,y+size*.49),color,3)
        s.line((x+size*.35,y+size*.67,x+size*.65,y+size*.67),color,2)
    else:
        points = []
        for i in range(16):
            angle = pi*(.82+1.36*i/15)
            points.extend((x+size*.5+size*.30*cos(angle), y+size*.52+size*.30*sin(angle)))
        if kind == 'rotation_left':
            points[::2] = [2*x+size-v for v in points[::2]]
        s.line(points,color,2.2)
        a,b=points[-2:]
        dx,dy=a-points[-4],b-points[-3]
        norm=max(.001,(dx*dx+dy*dy)**.5)
        dx,dy=dx/norm*size*.17,dy/norm*size*.17
        s.poly((a+dx*.35,b+dy*.35,a-dx-dy*.72,b-dy+dx*.72,a-dx+dy*.72,b-dy-dx*.72),color)
