#!/usr/bin/env python3
"""Ninja-CLI — a terminal 1v1 fighting game (punch / kick / block) inspired by Shadow Fight.

Player vs AI. Real-time combat in the terminal using curses.

Controls:
    a / d        move left / right
    w / up       jump    (dodges low attacks / kicks)
    s / down     crouch  (hold — dodges high attacks / punches)
    j            punch   (fast, short range, low damage, HIGH — whiffs on crouch)
    k            kick    (slow, long range, high damage, LOW — whiffs on jump)
    space / l    block   (hold to reduce incoming damage)
    q            quit

Run:  python3 ninja.py
"""

import curses
import random
import time

# --- Tunables -------------------------------------------------------------
FPS = 30
FRAME = 1.0 / FPS

ARENA_MIN = 2               # left wall (x column offset inside the arena)
MAX_HP = 100

MOVE_SPEED = 1              # columns per move tick
MOVE_COOLDOWN = 0.05        # seconds between move steps

# attack -> (windup, active, recovery, reach, damage, level)
# level "high" whiffs on a crouching foe; level "low" whiffs on an airborne foe.
ATTACKS = {
    "punch": dict(windup=0.05, active=0.08, recovery=0.18, reach=6, damage=8, level="high"),
    "kick":  dict(windup=0.14, active=0.10, recovery=0.34, reach=9, damage=16, level="low"),
}
BLOCK_REDUCTION = 0.8       # 80% damage blocked
HITSTUN = 0.22              # seconds a fighter is stunned after being hit

JUMP_TIME = 0.55            # seconds airborne per jump
JUMP_HEIGHT = 5             # peak rows above the ground

GRAVITY = 60.0              # rows/sec^2 pulling particles down
MAX_PARTICLES = 200         # hard cap so long fights stay snappy


class Fighter:
    def __init__(self, x, facing, name, is_ai=False):
        self.x = x
        self.facing = facing          # +1 faces right, -1 faces left
        self.name = name
        self.is_ai = is_ai
        self.hp = MAX_HP

        self.state = "idle"           # idle | windup | active | recovery | hitstun
        self.attack = None            # "punch" | "kick" while attacking
        self.state_until = 0.0
        self.has_hit = False          # attack already landed this swing?
        self.blocking = False

        self.airborne = False         # mid-jump?
        self.jump_start = 0.0
        self.jump_until = 0.0
        self.crouching = False

        self.last_move = 0.0
        self.ai_next_decision = 0.0

    # --- state helpers ---
    def busy(self):
        return self.state in ("windup", "active", "recovery", "hitstun")

    def height(self):
        if self.airborne:
            return "air"
        if self.crouching:
            return "crouch"
        return "stand"

    def jump_offset(self, now):
        """Rows above the ground right now (0 while grounded)."""
        if not self.airborne:
            return 0
        t = (now - self.jump_start) / JUMP_TIME
        t = max(0.0, min(1.0, t))
        return int(round(JUMP_HEIGHT * 4 * t * (1 - t)))   # parabolic arc

    def start_jump(self, now):
        if self.busy() or self.airborne or self.crouching:
            return
        self.airborne = True
        self.jump_start = now
        self.jump_until = now + JUMP_TIME

    def update_vertical(self, now):
        if self.airborne and now >= self.jump_until:
            self.airborne = False

    def hurt_x(self):
        """Column the fighter occupies for hit detection."""
        return self.x

    def attack_tip(self):
        """Furthest column the current active attack reaches."""
        reach = ATTACKS[self.attack]["reach"]
        return self.x + self.facing * reach

    def start_attack(self, kind, now):
        if self.busy() or self.blocking or self.airborne or self.crouching:
            return
        self.attack = kind
        self.state = "windup"
        self.has_hit = False
        self.state_until = now + ATTACKS[kind]["windup"]

    def take_hit(self, dmg, now):
        if self.blocking:
            dmg *= (1 - BLOCK_REDUCTION)
        self.hp = max(0, self.hp - dmg)
        # heavy interrupts: getting hit cancels your swing / jump into hitstun
        self.state = "hitstun"
        self.attack = None
        self.airborne = False
        self.state_until = now + HITSTUN

    def update_state(self, now):
        if now < self.state_until:
            return
        if self.state == "windup":
            self.state = "active"
            self.state_until = now + ATTACKS[self.attack]["active"]
        elif self.state == "active":
            self.state = "recovery"
            self.state_until = now + ATTACKS[self.attack]["recovery"]
        elif self.state in ("recovery", "hitstun"):
            self.state = "idle"
            self.attack = None


class Particle:
    """A short-lived spark of blood (hit) or sweat (block) flung from an impact."""

    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "blood")

    def __init__(self, x, y, vx, vy, life, blood):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.blood = blood

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += GRAVITY * dt
        self.life -= dt

    def dead(self, ground_y):
        return self.life <= 0 or self.y > ground_y

    def glyph(self):
        """Denser mark when fresh, thinning out as it fades."""
        frac = self.life / self.max_life if self.max_life else 0
        if self.blood:
            table = ["*", "o", "*", ".", "·", "`"]
        else:
            table = ["+", "x", "*", ".", "·", "`"]
        idx = int((1 - frac) * (len(table) - 1))
        return table[max(0, min(len(table) - 1, idx))]


def spawn_burst(particles, x, y, direction, blood):
    """Fling a burst of particles from (x, y) mostly along `direction` (+1/-1)."""
    n = 10 if blood else 6
    for _ in range(n):
        speed = random.uniform(6, 22)
        vx = direction * speed + random.uniform(-6, 6)
        vy = random.uniform(-22, -4)            # kick upward, gravity pulls back
        life = random.uniform(0.30, 0.65)
        particles.append(Particle(float(x), float(y), vx, vy, life, blood))
    if len(particles) > MAX_PARTICLES:
        del particles[:-MAX_PARTICLES]


class DamageNumber:
    """A damage figure that floats up from an impact and fades out."""

    __slots__ = ("x", "y", "vy", "life", "max_life", "text", "blocked")

    def __init__(self, x, y, text, blocked):
        self.x = float(x)
        self.y = float(y)
        self.vy = -6.0                 # rows/sec upward
        self.life = 0.8
        self.max_life = 0.8
        self.text = text
        self.blocked = blocked

    def update(self, dt):
        self.y += self.vy * dt
        self.vy += 3.0 * dt            # ease the rise
        self.life -= dt

    def dead(self):
        return self.life <= 0


def spawn_damage(popups, x, y, dmg, blocked):
    text = str(int(round(dmg))) if not blocked else f"-{int(round(dmg))}"
    popups.append(DamageNumber(x, y, text, blocked))


def gap(a, b):
    return abs(a.x - b.x)


def try_move(f, direction, now, other, left_wall, right_wall):
    if f.busy() or f.crouching:
        return
    if now - f.last_move < MOVE_COOLDOWN:
        return
    nx = f.x + direction * MOVE_SPEED
    nx = max(left_wall, min(right_wall, nx))
    # no walking through the opponent
    if abs(nx - other.x) < 3:
        return
    f.x = nx
    f.last_move = now


def ai_think(ai, foe, now, left_wall, right_wall):
    """Simple reactive AI: close distance, block threats, punish openings."""
    if now < ai.ai_next_decision:
        # keep blocking decision alive between decisions if foe is swinging
        ai.blocking = foe.state in ("windup", "active") and gap(ai, foe) <= 10 and random.random() < 0.85
        return

    ai.ai_next_decision = now + random.uniform(0.08, 0.22)
    d = gap(ai, foe)

    # face the foe
    if not ai.airborne:
        ai.facing = 1 if foe.x > ai.x else -1

    # let an in-progress jump finish
    if ai.airborne:
        return

    # defend when the player is attacking in range
    if foe.state in ("windup", "active") and d <= 11:
        lvl = ATTACKS[foe.attack]["level"] if foe.attack else None
        r = random.random()
        ai.blocking = False
        ai.crouching = False
        if lvl == "low" and r < 0.55 and not ai.busy():
            ai.start_jump(now)          # hop over the kick
            return
        if lvl == "high" and r < 0.55 and not ai.busy():
            ai.crouching = True         # duck under the punch
            return
        ai.blocking = r < 0.7
        if ai.blocking:
            return
    else:
        ai.blocking = False
        ai.crouching = False

    if ai.busy():
        return

    if d <= ATTACKS["punch"]["reach"]:
        # in range: mix punches and kicks
        ai.start_attack("kick" if random.random() < 0.4 else "punch", now)
    elif d <= ATTACKS["kick"]["reach"]:
        if random.random() < 0.5:
            ai.start_attack("kick", now)
        else:
            try_move(ai, ai.facing, now, foe, left_wall, right_wall)
    else:
        # close the distance
        try_move(ai, ai.facing, now, foe, left_wall, right_wall)


def resolve_hits(a, b, now, particles=None, ground_y=0, popups=None):
    """If a fighter is in its active frame and the foe is in reach, land the hit once."""
    for atk, foe in ((a, b), (b, a)):
        if atk.state == "active" and not atk.has_hit:
            tip = atk.attack_tip()
            # foe is hit if within the swept range in front of the attacker
            lo, hi = sorted((atk.x, tip))
            in_range = lo - 1 <= foe.x <= hi + 1
            level = ATTACKS[atk.attack]["level"]
            # vertical dodge: high whiffs on crouch, low whiffs on jump
            dodged = (level == "high" and foe.height() == "crouch") or \
                     (level == "low" and foe.height() == "air")
            if in_range and not dodged:
                blocked = foe.blocking
                before = foe.hp
                foe.take_hit(ATTACKS[atk.attack]["damage"], now)
                atk.has_hit = True
                dealt = before - foe.hp
                # impact roughly at torso height, lifted if the foe is airborne
                hit_y = ground_y - 2 - foe.jump_offset(now)
                if particles is not None:
                    spawn_burst(particles, foe.x + 1, hit_y,
                                direction=atk.facing, blood=not blocked)
                if popups is not None:
                    spawn_damage(popups, foe.x + 1, hit_y - 1, dealt, blocked)


# --- Rendering ------------------------------------------------------------

# Poses drawn facing RIGHT (top -> bottom); mirror() flips them for facing left.
POSES = {
    "idle":    [" O ", "/|\\", " | ", "/ \\"],
    "block":   [" O ", " |]", " |]", "/ \\"],
    "punch":   [" O   ", " |-->", " |   ", "/ \\ "],
    "kick":    [" O  ", "/|  ", " |=>", "/   "],
    "hitstun": [" x ", "\\|/", "/ \\"],
    "crouch":  [" o ", "/=\\"],
    "air":     ["\\o/", " | ", "> <"],
}
_MIRROR = str.maketrans("/\\<>()[]{}", "\\/><)(][}{")


def mirror(lines):
    return [ln[::-1].translate(_MIRROR) for ln in lines]


def sprite(f):
    """Return the ascii art lines for the fighter's current pose (top to bottom)."""
    if f.state == "hitstun":
        pose = "hitstun"
    elif f.crouching:
        pose = "crouch"
    elif f.airborne:
        pose = "air"
    elif f.blocking:
        pose = "block"
    elif f.state in ("windup", "active") and f.attack == "punch":
        pose = "punch"
    elif f.state in ("windup", "active") and f.attack == "kick":
        pose = "kick"
    else:
        pose = "idle"
    art = POSES[pose]
    return art if f.facing > 0 else mirror(art)


def draw_bar(win, y, x, label, hp, width, color):
    filled = int(round(width * hp / MAX_HP))
    win.addstr(y, x, f"{label} ", curses.A_BOLD)
    bar_x = x + len(label) + 1
    win.addstr(y, bar_x, "[")
    win.addstr(y, bar_x + 1, "█" * filled, color)
    win.addstr(y, bar_x + 1 + filled, " " * (width - filled))
    win.addstr(y, bar_x + 1 + width, f"] {int(hp):3d}")


def draw(win, player, ai, ground_y, now=0.0, msg=None, particles=None, popups=None):
    win.erase()
    h, w = win.getmaxyx()

    green = curses.color_pair(1)
    red = curses.color_pair(2)
    cyan = curses.color_pair(3)
    yellow = curses.color_pair(4)
    white = curses.color_pair(5)

    # title + health bars
    bar_w = max(10, (w - 20) // 2 - 8)
    draw_bar(win, 1, 2, "P1", player.hp, bar_w, green)
    draw_bar(win, 1, w - (bar_w + 12), "AI", ai.hp, bar_w, red)
    win.addstr(0, max(0, (w - 9) // 2), "NINJA-CLI", curses.A_BOLD | cyan)

    # ground
    win.hline(ground_y + 1, 1, curses.ACS_HLINE, w - 2)

    # fighters (draw sprite bottom-aligned to ground, lifted while airborne)
    for f, col in ((player, cyan), (ai, yellow)):
        lines = sprite(f)
        yoff = f.jump_offset(now)
        for i, line in enumerate(lines):
            y = ground_y - (len(lines) - 1) + i - yoff
            x = int(f.x)
            if 0 <= y < h and 0 <= x < w - len(line):
                attr = col | curses.A_BOLD
                if f.state == "hitstun":
                    attr = red | curses.A_BOLD
                win.addstr(y, x, line, attr)

    # particles (blood / sparks) drawn over the fighters
    if particles:
        for p in particles:
            px, py = int(p.x), int(round(p.y))
            if 0 <= py < h and 0 <= px < w - 1:
                attr = (red if p.blood else white) | curses.A_BOLD
                try:
                    win.addstr(py, px, p.glyph(), attr)
                except curses.error:
                    pass

    # floating damage numbers (on top of everything)
    if popups:
        for d in popups:
            py = int(round(d.y))
            px = int(round(d.x - len(d.text) / 2))
            if 0 <= py < h and 0 <= px < w - len(d.text):
                if d.blocked:
                    attr = white | curses.A_DIM
                else:
                    frac = d.life / d.max_life if d.max_life else 0
                    attr = (red | curses.A_BOLD) if frac > 0.4 else (yellow | curses.A_BOLD)
                try:
                    win.addstr(py, px, d.text, attr)
                except curses.error:
                    pass

    # hint / message line
    hint = "a/d move  w jump  s crouch  j punch  k kick  space block  q quit"
    win.addstr(ground_y + 2, 2, hint[: w - 4], curses.A_DIM)
    if msg:
        win.addstr(ground_y // 2, max(0, (w - len(msg)) // 2), msg,
                   curses.A_BOLD | curses.A_REVERSE)

    win.noutrefresh()
    curses.doupdate()


# --- Main loop ------------------------------------------------------------

def game(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_RED, -1)
    curses.init_pair(3, curses.COLOR_CYAN, -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)
    curses.init_pair(5, curses.COLOR_WHITE, -1)

    h, w = stdscr.getmaxyx()
    if w < 50 or h < 12:
        stdscr.nodelay(False)
        stdscr.addstr(0, 0, "Terminal too small. Resize to at least 50x12 and rerun.")
        stdscr.getch()
        return

    left_wall = ARENA_MIN
    right_wall = w - 6
    ground_y = h - 4

    player = Fighter(x=w // 3, facing=1, name="P1")
    ai = Fighter(x=2 * w // 3, facing=-1, name="AI", is_ai=True)

    # countdown
    for n in ("3", "2", "1", "FIGHT!"):
        draw(stdscr, player, ai, ground_y, now=0.0, msg=f"  {n}  ")
        time.sleep(0.5)

    winner = None
    particles = []
    popups = []
    last = time.perf_counter()

    while winner is None:
        now = time.perf_counter()

        # --- input (drain buffer) ---
        held_block = False
        held_crouch = False
        while True:
            c = stdscr.getch()
            if c == -1:
                break
            if c in (ord("q"), 27):
                return
            elif c in (ord("a"), curses.KEY_LEFT):
                try_move(player, -1, now, ai, left_wall, right_wall)
            elif c in (ord("d"), curses.KEY_RIGHT):
                try_move(player, 1, now, ai, left_wall, right_wall)
            elif c in (ord("w"), curses.KEY_UP):
                player.start_jump(now)
            elif c in (ord("s"), curses.KEY_DOWN):
                held_crouch = True
            elif c == ord("j"):
                player.start_attack("punch", now)
            elif c == ord("k"):
                player.start_attack("kick", now)
            elif c in (ord(" "), ord("l")):
                held_block = True

        # crouch/block are momentary holds; can't do either mid-swing or mid-air
        player.crouching = held_crouch and not player.busy() and not player.airborne
        player.blocking = held_block and not player.busy() and not player.airborne \
            and not player.crouching

        # keep player facing the AI
        player.facing = 1 if ai.x > player.x else -1

        # --- AI ---
        ai_think(ai, player, now, left_wall, right_wall)

        # --- state machines ---
        player.update_state(now)
        ai.update_state(now)
        player.update_vertical(now)
        ai.update_vertical(now)

        # --- combat ---
        resolve_hits(player, ai, now, particles, ground_y, popups)

        # --- particles + damage popups ---
        for p in particles:
            p.update(FRAME)
        particles[:] = [p for p in particles if not p.dead(ground_y + 1)]
        for d in popups:
            d.update(FRAME)
        popups[:] = [d for d in popups if not d.dead()]

        # --- win check ---
        if player.hp <= 0 and ai.hp <= 0:
            winner = "DRAW"
        elif ai.hp <= 0:
            winner = "P1 WINS!"
        elif player.hp <= 0:
            winner = "AI WINS!"

        draw(stdscr, player, ai, ground_y, now=now, particles=particles, popups=popups)

        # --- frame pacing ---
        dt = time.perf_counter() - last
        if dt < FRAME:
            time.sleep(FRAME - dt)
        last = time.perf_counter()

    # end screen
    stdscr.nodelay(False)
    draw(stdscr, player, ai, ground_y, now=time.perf_counter(),
         msg=f"  {winner}  press any key  ")
    stdscr.getch()


def main():
    try:
        curses.wrapper(game)
    except KeyboardInterrupt:
        pass
    print("Thanks for playing Ninja-CLI!")


if __name__ == "__main__":
    main()
