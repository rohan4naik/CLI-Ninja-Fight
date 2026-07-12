#!/usr/bin/env python3
"""Ninja-CLI — a terminal 1v1 fighting game (punch / kick / block) inspired by Shadow Fight.

Player vs AI. Real-time combat in the terminal using curses.

Controls:
    a / d        move left / right  (momentum — tap to accelerate, glide to stop)
    w / up       jump    (real gravity arc; dodges low attacks / kicks)
    s / down     crouch  (hold — dodges high attacks / punches)
    j            punch   (fast, short range, low damage, HIGH — whiffs on crouch)
    k            kick    (slow, long range, high damage, LOW — whiffs on jump)
    space / l    block   (hold: chip + drain; TIME it to the hit for a parry)
    g            grab    (throw; beats a block, whiffs on a jumper)
    q            quit

Run:  python3 ninja.py
"""

import curses
import random
import time

# --- Tunables -------------------------------------------------------------
FPS = 60
FRAME = 1.0 / FPS

ARENA_MIN = 2               # left wall (x column offset inside the arena)
MAX_HP = 100
MIN_GAP = 3                 # closest two bodies can stand (columns)

# --- Movement physics (velocity + friction, in columns/second) ------------
MOVE_IMPULSE = 24.0         # velocity added per move input
MAX_VX = 30.0               # top horizontal speed
GROUND_FRICTION = 11.0      # decel coefficient on the ground (higher = grippier)
AIR_FRICTION = 1.6          # much less drag mid-air -> committed jumps
AIR_CONTROL = 0.30          # fraction of move impulse usable while airborne

# --- Jump physics (rows/second, rows/second^2) ----------------------------
JUMP_V0 = 26.0             # launch velocity
JUMP_GRAVITY = 68.0        # pulls the fighter back down

# attack -> (windup, active, recovery, reach, damage, level, knockback, stamina)
# level "high" whiffs on a crouching foe; level "low" whiffs on an airborne foe.
# "grab" is a throw: it beats a block but whiffs on an airborne (jumping) foe.
# punch and kick share the same reach — they differ in speed / damage / height.
STRIKE_REACH = 7
ATTACKS = {
    "punch": dict(windup=0.05, active=0.08, recovery=0.18, reach=STRIKE_REACH,
                  damage=8, level="high", knockback=9.0, stamina=10),
    "kick":  dict(windup=0.14, active=0.10, recovery=0.34, reach=STRIKE_REACH,
                  damage=16, level="low", knockback=20.0, stamina=22),
    "grab":  dict(windup=0.18, active=0.06, recovery=0.42, reach=4,
                  damage=26, level="grab", knockback=7.0, stamina=30),
}
GRAB_KNOCKDOWN = 0.55       # foe is floored (long stun) after a slam
# --- AI difficulty ---------------------------------------------------------
# react   : (min, max) seconds between offensive decisions (higher = slower/dumber)
# read    : scales dodge/block success vs an incoming attack (lower = whiffs defense)
# punish  : chance to punish a whiffed recovery (0 = never dashes in for free hits)
# aggr    : offensive commitment as (winning, neutral, losing)
# mistake : chance per decision to freeze up and do nothing
# dmg     : AI outgoing damage multiplier
DIFFICULTY = {
    "EASY":   dict(react=(0.30, 0.55), read=0.35, punish=0.25,
                   aggr=(0.30, 0.40, 0.50), mistake=0.35, dmg=0.65),
    "MEDIUM": dict(react=(0.14, 0.28), read=0.62, punish=0.65,
                   aggr=(0.45, 0.60, 0.75), mistake=0.12, dmg=0.9),
    "HARD":   dict(react=(0.05, 0.14), read=0.88, punish=1.0,
                   aggr=(0.60, 0.75, 0.90), mistake=0.0, dmg=1.0),
}

# --- Defense --------------------------------------------------------------
# A held block is a spectrum, not a switch:
#   * raise guard JUST as the blow lands  -> PARRY: no damage, attacker staggered
#   * hold a steady guard with stamina    -> BLOCK: chip damage + pushback
#   * block with the tank near empty       -> GUARD BREAK: guard shatters, big stun
BLOCK_REDUCTION = 0.78      # steady block soaks 78% of the damage; the rest chips
BLOCK_KB_SCALE = 0.35       # blocked hits shove far less
HITSTUN = 0.22             # seconds a fighter is stunned after being hit

PARRY_WINDOW = 0.14         # perfect-block window, measured from when guard rose
PARRY_STAM_REFUND = 30.0    # a clean parry pays its stamina back, and then some
PARRY_KB = 7.0              # the parried attacker is shoved off their own swing
PARRY_STAGGER = 0.50        # ...and frozen wide open — the reward for good timing
BLOCK_HIT_STAM = 12.0       # base stamina to soak one blocked hit
BLOCK_HIT_STAM_SCALE = 0.7  # + this much per point of raw incoming damage
GUARDBREAK_DMG = 0.55       # fraction of raw damage that leaks through a broken guard
GUARDBREAK_STUN = 0.55      # long, fully-punishable stun when the guard shatters
BLOCK_LOCK = 0.11           # guard recoil: can't counter-attack for this long
PARRY_AI_SKILL = 0.7        # scales an AI's read into its odds of trying a late parry

# --- Combat feel ----------------------------------------------------------
HITSTOP_CLEAN = 0.07        # global freeze frames on a clean hit
HITSTOP_HEAVY = 0.10        # kicks bite harder
HITSTOP_BLOCK = 0.035       # blocked hits barely hitch
SHAKE_PUNCH = 1.3
SHAKE_KICK = 2.4
SHAKE_BLOCK = 0.6
SHAKE_DECAY = 22.0          # how fast the shake settles (per second)

# --- Stamina --------------------------------------------------------------
MAX_STAM = 100.0
JUMP_STAM = 16.0
BLOCK_DRAIN = 42.0          # per second while holding block
STAM_REGEN = 34.0           # per second, recovered when not spending

GRAVITY = 60.0              # rows/sec^2 pulling particles down
MAX_PARTICLES = 200         # hard cap so long fights stay snappy


class Fighter:
    def __init__(self, x, facing, name, is_ai=False):
        self.x = float(x)
        self.vx = 0.0                 # horizontal velocity (cols/sec)
        self.facing = facing          # +1 faces right, -1 faces left
        self.name = name
        self.is_ai = is_ai
        self.hp = MAX_HP
        self.dmg_scale = 1.0          # outgoing damage multiplier (AI difficulty)
        self.stamina = MAX_STAM
        self.spent_stamina = False    # spent stamina this frame? (blocks regen)

        self.state = "idle"           # idle | windup | active | recovery | hitstun
        self.attack = None            # "punch" | "kick" while attacking
        self.state_until = 0.0
        self.has_hit = False          # attack already landed this swing?
        self.blocking = False
        self.was_blocking = False     # guard state last frame (to time the parry window)
        self.block_start = -1.0       # gt when the guard was raised
        self.block_lock_until = 0.0   # guard recoil: no counter-attack until this
        self.parry_flash = 0.0        # gt until which to draw the parry flash

        self.airborne = False         # mid-jump?
        self.height = 0.0             # rows above the ground
        self.vy = 0.0                 # vertical velocity (rows/sec, +up)
        self.crouching = False

        self.ai_next_decision = 0.0
        self.threat_seen = False       # AI: already reacted to the current incoming attack?
        self.parry_armed = False       # AI: committed to a late parry on this attack?

    # --- state helpers ---
    def busy(self):
        return self.state in ("windup", "active", "recovery", "hitstun")

    def height_level(self):
        if self.airborne and self.height >= 1.5:
            return "air"
        if self.crouching:
            return "crouch"
        return "stand"

    def jump_offset(self):
        """Rows above the ground right now (0 while grounded)."""
        return int(round(self.height))

    def can_spend(self, cost):
        return self.stamina >= cost

    def spend(self, cost):
        self.stamina = max(0.0, self.stamina - cost)
        self.spent_stamina = True

    def start_jump(self, now):
        if self.busy() or self.airborne or self.crouching:
            return
        if not self.can_spend(JUMP_STAM):
            return
        self.spend(JUMP_STAM)
        self.airborne = True
        self.height = 0.0
        self.vy = JUMP_V0

    def update_vertical(self, dt):
        if not self.airborne:
            return
        self.vy -= JUMP_GRAVITY * dt
        self.height += self.vy * dt
        if self.height <= 0.0 and self.vy < 0.0:
            self.height = 0.0
            self.vy = 0.0
            self.airborne = False

    def apply_move(self, direction):
        """Add a velocity impulse; damped and clamped. Weaker mid-air."""
        if self.busy() or self.crouching:
            return
        imp = MOVE_IMPULSE * (AIR_CONTROL if self.airborne else 1.0)
        self.vx += direction * imp
        self.vx = max(-MAX_VX, min(MAX_VX, self.vx))

    def integrate_horizontal(self, dt, left_wall, right_wall):
        # friction settles velocity toward zero
        fr = AIR_FRICTION if self.airborne else GROUND_FRICTION
        self.vx -= self.vx * min(1.0, fr * dt)
        if abs(self.vx) < 0.05:
            self.vx = 0.0
        self.x += self.vx * dt
        if self.x <= left_wall:
            self.x = left_wall
            if self.vx < 0:
                self.vx = 0.0
        elif self.x >= right_wall:
            self.x = right_wall
            if self.vx > 0:
                self.vx = 0.0

    def attack_tip(self):
        """Furthest column the current active attack reaches."""
        reach = ATTACKS[self.attack]["reach"]
        return self.x + self.facing * reach

    def start_attack(self, kind, now):
        if self.busy() or self.blocking or self.airborne or self.crouching:
            return
        if now < self.block_lock_until:   # still recoiling from a blocked hit
            return
        if not self.can_spend(ATTACKS[kind]["stamina"]):
            return
        self.spend(ATTACKS[kind]["stamina"])
        self.attack = kind
        self.state = "windup"
        self.has_hit = False
        self.state_until = now + ATTACKS[kind]["windup"]

    def guard_outcome(self, now, raw_dmg):
        """Classify an incoming hit against a raised guard: parry / block / guardbreak."""
        if now - self.block_start <= PARRY_WINDOW:
            return "parry"
        if self.stamina < BLOCK_HIT_STAM + raw_dmg * BLOCK_HIT_STAM_SCALE:
            return "guardbreak"
        return "block"

    def get_parried(self, now):
        """Frozen wide open after the foe perfect-blocks: the swing eats itself."""
        self.attack = None
        self.has_hit = True
        self.state = "recovery"
        self.state_until = now + PARRY_STAGGER
        self.vx = -self.facing * PARRY_KB   # shoved back off the parried swing

    def take_hit(self, dmg, now, knockback, guard="clean"):
        """Apply a strike. guard in {clean, block, guardbreak}; parry is handled
        by the attacker's get_parried() and never reaches here."""
        if guard == "block":
            # steady guard: chip damage + pushback, but footing and guard hold
            self.spend(BLOCK_HIT_STAM + dmg * BLOCK_HIT_STAM_SCALE)
            self.hp = max(0, self.hp - dmg * (1 - BLOCK_REDUCTION))
            self.vx = knockback * BLOCK_KB_SCALE
            self.block_lock_until = now + BLOCK_LOCK
            return
        if guard == "guardbreak":
            # the guard shatters: partial damage now, long punishable stun
            dmg *= GUARDBREAK_DMG
            self.blocking = False
            self.block_start = -1.0
        # clean hit or shattered guard: heavy interrupt into hitstun / knockdown
        self.hp = max(0, self.hp - dmg)
        self.state = "hitstun"
        self.attack = None
        self.airborne = False
        self.height = 0.0
        self.vy = 0.0
        self.vx = knockback          # shoved back along the punch direction
        self.state_until = now + (GUARDBREAK_STUN if guard == "guardbreak"
                                  else HITSTUN)

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

    def regen(self, dt):
        if not self.spent_stamina:
            rate = STAM_REGEN * (1.4 if self.state == "idle" else 1.0)
            self.stamina = min(MAX_STAM, self.stamina + rate * dt)
        self.spent_stamina = False


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

    __slots__ = ("x", "y", "vy", "life", "max_life", "text", "kind")

    def __init__(self, x, y, text, kind):
        self.x = float(x)
        self.y = float(y)
        self.vy = -6.0                 # rows/sec upward
        self.life = 0.8
        self.max_life = 0.8
        self.text = text
        self.kind = kind               # clean | block | parry | guardbreak

    def update(self, dt):
        self.y += self.vy * dt
        self.vy += 3.0 * dt            # ease the rise
        self.life -= dt

    def dead(self):
        return self.life <= 0


def spawn_damage(popups, x, y, dmg, kind="clean"):
    if kind == "parry":
        text = "PARRY!"
    elif kind == "guardbreak":
        text = f"BREAK -{int(round(dmg))}"
    elif kind == "block":
        text = f"-{int(round(dmg))}"
    else:
        text = str(int(round(dmg)))
    popups.append(DamageNumber(x, y, text, kind))


def gap(a, b):
    return abs(a.x - b.x)


def grab_connects(atk, foe):
    """A throw lands if the (grounded) foe is within grab reach in front of atk.
    Jumping is the escape — an airborne foe can't be grabbed."""
    if foe.height_level() == "air":
        return False
    reach = ATTACKS["grab"]["reach"]
    lo, hi = sorted((atk.x, atk.x + atk.facing * reach))
    return lo - 1 <= foe.x <= hi + 1


def resolve_collision(a, b, left_wall, right_wall):
    """Two grounded bodies can't share space — shove them apart symmetrically."""
    # jumping fighters pass over each other
    if (a.airborne and a.height >= 2) or (b.airborne and b.height >= 2):
        return
    dx = b.x - a.x
    dist = abs(dx)
    if dist >= MIN_GAP:
        return
    overlap = MIN_GAP - dist
    sign = 1.0 if dx >= 0 else -1.0
    a.x = max(left_wall, min(right_wall, a.x - sign * overlap / 2))
    b.x = max(left_wall, min(right_wall, b.x + sign * overlap / 2))
    # kill the velocity driving them together
    if a.vx * sign > 0:
        a.vx = 0.0
    if b.vx * sign < 0:
        b.vx = 0.0


def ai_think(ai, foe, now, left_wall, right_wall, diff):
    """Reactive AI: reads spacing, blocks/dodges threats, punishes whiffs, baits.

    `diff` is a DIFFICULTY entry — it scales reaction speed, defense reads,
    whiff-punishing, aggression, and how often the AI just freezes up.
    """
    # adaptive aggression: press harder when behind, patient when ahead
    win_a, neu_a, lose_a = diff["aggr"]
    losing = ai.hp < foe.hp - 5
    winning = ai.hp > foe.hp + 15
    aggression = lose_a if losing else (win_a if winning else neu_a)

    # air-control toward the foe, then let the jump play out
    if ai.airborne:
        if now >= ai.ai_next_decision:
            ai.ai_next_decision = now + 0.05
            ai.facing = 1 if foe.x > ai.x else -1
            ai.apply_move(ai.facing)
        return

    d = gap(ai, foe)
    foe_lvl = ATTACKS[foe.attack]["level"] if foe.attack else None
    foe_threat = foe.state in ("windup", "active") and d <= 12

    # --- reaction to an incoming attack runs every frame (fast defense) ---
    if foe_threat:
        read = diff["read"]                # easy AI often fails to react in time
        r = random.random()
        if foe_lvl == "low" and r < 0.55 * read and ai.can_spend(JUMP_STAM):
            ai.blocking = ai.crouching = False
            ai.start_jump(now)             # hop over the kick
            return
        if foe_lvl == "high" and r < 0.6 * read:
            ai.blocking = False
            ai.crouching = True            # duck under the punch
            return
        ai.crouching = False
        if foe.state == "windup":
            # decide once, when the attack starts, whether to go for a late parry
            if not ai.threat_seen:
                ai.threat_seen = True
                ai.parry_armed = random.random() < read * PARRY_AI_SKILL
            if ai.parry_armed:
                ai.blocking = False        # bait it: hold guard down through the windup
                return
            ai.blocking = r < 0.85 * read  # otherwise just turtle up early
            if ai.blocking:
                return
        else:
            # active frame: a parry-armed AI snaps its guard up right now
            if ai.parry_armed:
                ai.blocking = True         # fresh guard raise -> lands in the parry window
                return
            ai.blocking = r < 0.9 * read
            if ai.blocking:
                return
    else:
        ai.threat_seen = False
        ai.parry_armed = False
        ai.blocking = False
        ai.crouching = False

    # throttle offensive decisions (reaction time varies by difficulty)
    if now < ai.ai_next_decision:
        return
    lo, hi = diff["react"]
    ai.ai_next_decision = now + random.uniform(lo, hi)

    ai.facing = 1 if foe.x > ai.x else -1
    if ai.busy():
        return

    # easy/medium AI sometimes just freezes — a free opening for the player
    if random.random() < diff["mistake"]:
        return

    punch_reach = ATTACKS["punch"]["reach"]
    kick_reach = ATTACKS["kick"]["reach"]
    grab_reach = ATTACKS["grab"]["reach"]

    # --- break a turtle: grab a blocking foe within throw range ---
    if foe.blocking and d <= grab_reach and ai.can_spend(ATTACKS["grab"]["stamina"]) \
            and random.random() < aggression:
        ai.start_attack("grab", now)
        return

    # --- whiff punish: foe stuck in recovery is a free hit ---
    if foe.state == "recovery" and random.random() < diff["punish"]:
        if d <= punch_reach + 1 and ai.can_spend(ATTACKS["punch"]["stamina"]):
            ai.start_attack("punch", now)
            return
        if d <= kick_reach + 1 and ai.can_spend(ATTACKS["kick"]["stamina"]):
            ai.start_attack("kick", now)
            return
        ai.apply_move(ai.facing)           # dash in to punish
        return

    # --- low stamina: back off and recover instead of whiffing ---
    if ai.stamina < ATTACKS["punch"]["stamina"]:
        ai.apply_move(-ai.facing)
        return

    # --- spacing game: sit at the tip of kick range, dart in on openings ---
    ideal = kick_reach - 1
    if d > ideal + 2:
        ai.apply_move(ai.facing)           # close the gap
    elif d < punch_reach - 1:
        # crowded: jab or reset spacing
        if random.random() < aggression and ai.can_spend(ATTACKS["punch"]["stamina"]):
            ai.start_attack("punch", now)
        else:
            ai.apply_move(-ai.facing)      # step back to breathe
    else:
        # in the pocket: kick if foe is idle/committed, else bait with a step
        if foe.state == "idle" and random.random() < aggression \
                and ai.can_spend(ATTACKS["kick"]["stamina"]):
            ai.start_attack("kick", now)
        elif random.random() < 0.35:
            ai.apply_move(-ai.facing)      # bait a whiff
        elif random.random() < aggression and ai.can_spend(ATTACKS["punch"]["stamina"]):
            ai.start_attack("punch", now)


def resolve_hits(a, b, now, particles=None, ground_y=0, popups=None):
    """Land active-frame hits once. Returns (hitstop_secs, shake_mag) for this frame."""
    hitstop = 0.0
    shake = 0.0
    for atk, foe in ((a, b), (b, a)):
        if atk.attack == "grab":
            continue                     # throws are resolved by the grab handler
        if atk.state == "active" and not atk.has_hit:
            tip = atk.attack_tip()
            lo, hi = sorted((atk.x, tip))
            in_range = lo - 1 <= foe.x <= hi + 1
            info = ATTACKS[atk.attack]
            level = info["level"]
            # vertical dodge: high whiffs on crouch, low whiffs on jump
            dodged = (level == "high" and foe.height_level() == "crouch") or \
                     (level == "low" and foe.height_level() == "air")
            if in_range and not dodged:
                raw = info["damage"] * atk.dmg_scale
                kb = atk.facing * info["knockback"]
                before = foe.hp
                outcome = foe.guard_outcome(now, raw) if foe.blocking else "clean"
                atk.has_hit = True
                hit_y = ground_y - 2 - foe.jump_offset()

                if outcome == "parry":
                    # perfect block: no damage, attacker eats a stagger, guard refunds
                    atk.get_parried(now)
                    foe.stamina = min(MAX_STAM, foe.stamina + PARRY_STAM_REFUND)
                    foe.parry_flash = now + 0.30
                    hitstop = max(hitstop, HITSTOP_HEAVY)   # a beefy freeze sells it
                    shake = max(shake, SHAKE_KICK)
                    if particles is not None:
                        spawn_burst(particles, foe.x + 1, hit_y,
                                    direction=-atk.facing, blood=False)
                    if popups is not None:
                        spawn_damage(popups, foe.x + 1, hit_y - 1, 0, "parry")
                    continue

                foe.take_hit(raw, now, kb, guard=outcome)
                dealt = before - foe.hp
                # combat-feel: freeze frames + screen shake scaled to the blow
                if outcome == "block":
                    hitstop = max(hitstop, HITSTOP_BLOCK)
                    shake = max(shake, SHAKE_BLOCK)
                elif outcome == "guardbreak":
                    hitstop = max(hitstop, HITSTOP_HEAVY)
                    shake = max(shake, SHAKE_KICK)
                else:
                    hitstop = max(hitstop, HITSTOP_HEAVY if atk.attack == "kick"
                                  else HITSTOP_CLEAN)
                    shake = max(shake, SHAKE_KICK if atk.attack == "kick"
                                else SHAKE_PUNCH)
                if particles is not None:
                    spawn_burst(particles, foe.x + 1, hit_y,
                                direction=atk.facing, blood=outcome != "block")
                if popups is not None:
                    spawn_damage(popups, foe.x + 1, hit_y - 1, dealt, outcome)
    return hitstop, shake


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
    "grab":    [" O__", "/|  ", " |  ", "/ \\"],   # reaching to seize the foe
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
    elif f.state in ("windup", "active") and f.attack == "grab":
        pose = "grab"
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


def draw_stam(win, y, x, stam, width, color):
    filled = int(round(width * stam / MAX_STAM))
    win.addstr(y, x, "SP [")
    win.addstr(y, x + 4, "▪" * filled, color)
    win.addstr(y, x + 4 + filled, "·" * (width - filled), curses.A_DIM)
    win.addstr(y, x + 4 + width, "]")


def draw(win, player, ai, ground_y, msg=None, particles=None, popups=None,
         shake=(0, 0), now=0.0):
    win.erase()
    h, w = win.getmaxyx()
    sy, sx = shake

    green = curses.color_pair(1)
    red = curses.color_pair(2)
    cyan = curses.color_pair(3)
    yellow = curses.color_pair(4)
    white = curses.color_pair(5)

    # title + health/stamina bars (HUD does not shake)
    bar_w = max(10, (w - 20) // 2 - 8)
    draw_bar(win, 1, 2, "P1", player.hp, bar_w, green)
    draw_bar(win, 1, w - (bar_w + 12), "AI", ai.hp, bar_w, red)
    draw_stam(win, 2, 2, player.stamina, min(bar_w, 24), cyan)
    sp_w = min(bar_w, 24)
    draw_stam(win, 2, w - (sp_w + 6), ai.stamina, sp_w, yellow)
    win.addstr(0, max(0, (w - 9) // 2), "NINJA-CLI", curses.A_BOLD | cyan)

    # ground (shakes with the arena)
    gy = ground_y + 1 + sy
    if 0 <= gy < h:
        win.hline(gy, 1, curses.ACS_HLINE, w - 2)

    # fighters (draw sprite bottom-aligned to ground, lifted while airborne)
    for f, col in ((player, cyan), (ai, yellow)):
        lines = sprite(f)
        yoff = f.jump_offset()
        for i, line in enumerate(lines):
            y = ground_y - (len(lines) - 1) + i - yoff + sy
            x = int(f.x) + sx
            if 0 <= y < h and 0 <= x < w - len(line):
                attr = col | curses.A_BOLD
                if f.state == "hitstun":
                    attr = red | curses.A_BOLD
                elif now < f.parry_flash:      # bright green flash on a clean parry
                    attr = green | curses.A_BOLD | curses.A_REVERSE
                try:
                    win.addstr(y, x, line, attr)
                except curses.error:
                    pass

    # particles (blood / sparks) drawn over the fighters
    if particles:
        for p in particles:
            px, py = int(p.x) + sx, int(round(p.y)) + sy
            if 0 <= py < h and 0 <= px < w - 1:
                attr = (red if p.blood else white) | curses.A_BOLD
                try:
                    win.addstr(py, px, p.glyph(), attr)
                except curses.error:
                    pass

    # floating damage numbers (on top of everything)
    if popups:
        for d in popups:
            py = int(round(d.y)) + sy
            px = int(round(d.x - len(d.text) / 2)) + sx
            if 0 <= py < h and 0 <= px < w - len(d.text):
                if d.kind == "parry":
                    attr = green | curses.A_BOLD
                elif d.kind == "guardbreak":
                    attr = yellow | curses.A_BOLD | curses.A_REVERSE
                elif d.kind == "block":
                    attr = white | curses.A_DIM
                else:
                    frac = d.life / d.max_life if d.max_life else 0
                    attr = (red | curses.A_BOLD) if frac > 0.4 else (yellow | curses.A_BOLD)
                try:
                    win.addstr(py, px, d.text, attr)
                except curses.error:
                    pass

    # hint / message line
    hint = ("a/d move  w jump  s crouch  j punch  k kick  g grab  "
            "space block (time it = PARRY)  q quit")
    win.addstr(ground_y + 2, 2, hint[: w - 4], curses.A_DIM)
    if msg:
        win.addstr(ground_y // 2, max(0, (w - len(msg)) // 2), msg,
                   curses.A_BOLD | curses.A_REVERSE)

    win.noutrefresh()
    curses.doupdate()


# --- KO finisher: the "kusti" slam ----------------------------------------

# Cinematic close-up poses (drawn facing right; mirror() flips them).
FIN_GRAB  = [" O_", "/| ", "/| ", "/ \\"]     # winner seizing the foe
FIN_LIFT  = ["\\O/", " | ", " | ", "/ \\"]     # winner hoisting overhead
FIN_SLAM  = [" O ", " |\\", "/|  ", "/ \\"]    # winner driving down
FIN_HELD  = [" | ", "/|\\", " X "]             # foe hoisted upside-down (head X low)
FIN_SPLAT = ["         ", "\\_ X _/", "‾‾‾‾‾‾‾"]  # foe crashed flat


def _blit(win, lines, cx, base_y, attr, sx=0, sy=0):
    """Draw center-aligned `lines` with their bottom row sitting on base_y."""
    h, w = win.getmaxyx()
    for i, ln in enumerate(lines):
        y = base_y - (len(lines) - 1) + i + sy
        x = cx - len(ln) // 2 + sx
        if 0 <= y < h and 0 <= x < w - len(ln):
            try:
                win.addstr(y, x, ln, attr)
            except curses.error:
                pass


def play_finisher(stdscr, winner, loser, ground_y):
    """Slow-motion close-up: winner grabs the loser, lifts them overhead, slams down."""
    h, w = stdscr.getmaxyx()
    cx = w // 2
    face = winner.facing or 1
    gy = ground_y + 2                       # give the slam a little more floor

    red = curses.color_pair(2)
    cyan = curses.color_pair(3)
    yellow = curses.color_pair(4)
    white = curses.color_pair(5)
    wcol = cyan if winner.name == "P1" else yellow

    particles = []
    LIFT_H = 6                              # rows the foe is hoisted above the ground

    def wpose(lines):
        return lines if face > 0 else mirror(lines)

    def hpose(lines):
        return lines if face > 0 else mirror(lines)

    def frame(w_lines, l_lines, l_h, banner=None, shake=0.0, dt=0.045):
        stdscr.erase()
        sx = random.randint(-2, 2) if shake > 0.4 else 0
        sy = random.randint(-1, 1) if shake > 1.2 else 0
        # dim ground line for the close-up
        if 0 <= gy + 1 + sy < h:
            stdscr.hline(gy + 1 + sy, 1, curses.ACS_HLINE, w - 2)
        # winner stands one step back from center; foe centred (over the winner)
        wx = cx - face * 2
        _blit(stdscr, wpose(w_lines), wx, gy, wcol | curses.A_BOLD, sx, sy)
        if l_lines is not None:
            _blit(stdscr, hpose(l_lines), cx, gy - int(round(l_h)),
                  red | curses.A_BOLD, sx, sy)
        for p in particles:
            px, py = int(p.x) + sx, int(round(p.y)) + sy
            if 0 <= py < h and 0 <= px < w - 1:
                try:
                    stdscr.addstr(py, px, p.glyph(), red | curses.A_BOLD)
                except curses.error:
                    pass
        if banner:
            by = max(1, gy // 2)
            stdscr.addstr(by, max(0, (w - len(banner)) // 2), banner,
                          curses.A_BOLD | curses.A_REVERSE | wcol)
        stdscr.noutrefresh()
        curses.doupdate()
        for p in particles:
            p.update(dt)
        particles[:] = [p for p in particles if not p.dead(gy + 1)]
        time.sleep(dt)

    # 1) GRAB — seize the stunned foe (still on the ground, slumped)
    for _ in range(7):
        frame(FIN_GRAB, POSES["hitstun"], 0, banner="  GOTCHA!  ", dt=0.05)

    # 2) LIFT — hoist overhead, slowing near the top for weight
    steps = 12
    for i in range(steps + 1):
        t = i / steps
        eased = 1 - (1 - t) * (1 - t)       # ease-out — heavy at the top
        frame(FIN_LIFT, FIN_HELD, LIFT_H * eased,
              banner="  KUSTI!  ", dt=0.045)

    # 3) HOLD — the crowd holds its breath
    for _ in range(6):
        frame(FIN_LIFT, FIN_HELD, LIFT_H, banner="  KUSTI!  ", dt=0.06)

    # 4) SLAM — drive them into the dirt, accelerating down
    steps = 5
    for i in range(1, steps + 1):
        t = i / steps
        drop = LIFT_H * (1 - t * t)          # ease-in — speeds up on the way down
        frame(FIN_SLAM, FIN_HELD, drop, banner="  KUSTI!  ", dt=0.03)

    # 5) IMPACT — dust and blood erupt, screen kicks hard
    spawn_burst(particles, cx, gy - 1, direction=face, blood=True)
    spawn_burst(particles, cx, gy - 1, direction=-face, blood=True)
    for i in range(10):
        frame(FIN_SLAM, FIN_SPLAT, 0, banner="  S L A M ! !  ",
              shake=2.6 * (1 - i / 10), dt=0.045)

    # 6) STAND TALL — the finish settles into the K.O.
    for _ in range(8):
        frame(FIN_LIFT, FIN_SPLAT, 0, banner="  K.O.  ", dt=0.06)


def play_throw(stdscr, attacker, foe, ground_y, p1, ai):
    """Quick in-arena kusti slam for a landed grab mid-fight (non-lethal).

    Shorter than the KO finisher and rendered at the fighters' position, with
    the HUD kept up for continuity.
    """
    h, w = stdscr.getmaxyx()
    face = attacker.facing or 1
    gy = ground_y
    cx = max(6, min(w - 6, int(attacker.x)))

    green = curses.color_pair(1)
    red = curses.color_pair(2)
    cyan = curses.color_pair(3)
    yellow = curses.color_pair(4)
    wcol = cyan if attacker.name == "P1" else yellow
    particles = []
    LIFT_H = 4

    def wp(lines):
        return lines if face > 0 else mirror(lines)

    def frame(w_lines, l_lines, l_h, banner=None, shake=0.0, dt=0.045):
        stdscr.erase()
        sx = random.randint(-2, 2) if shake > 0.4 else 0
        sy = random.randint(-1, 1) if shake > 1.2 else 0
        # HUD stays put
        bar_w = max(10, (w - 20) // 2 - 8)
        draw_bar(stdscr, 1, 2, "P1", p1.hp, bar_w, green)
        draw_bar(stdscr, 1, w - (bar_w + 12), "AI", ai.hp, bar_w, red)
        if 0 <= gy + 1 + sy < h:
            stdscr.hline(gy + 1 + sy, 1, curses.ACS_HLINE, w - 2)
        wx = cx - face * 2
        _blit(stdscr, wp(w_lines), wx, gy, wcol | curses.A_BOLD, sx, sy)
        if l_lines is not None:
            _blit(stdscr, wp(l_lines), cx, gy - int(round(l_h)),
                  red | curses.A_BOLD, sx, sy)
        for p in particles:
            px, py = int(p.x) + sx, int(round(p.y)) + sy
            if 0 <= py < h and 0 <= px < w - 1:
                try:
                    stdscr.addstr(py, px, p.glyph(), red | curses.A_BOLD)
                except curses.error:
                    pass
        if banner:
            stdscr.addstr(max(1, gy // 2), max(0, (w - len(banner)) // 2),
                          banner, curses.A_BOLD | curses.A_REVERSE | wcol)
        stdscr.noutrefresh()
        curses.doupdate()
        for p in particles:
            p.update(dt)
        particles[:] = [p for p in particles if not p.dead(gy + 1)]
        time.sleep(dt)

    # hoist
    for i in range(1, 7):
        t = i / 6
        frame(FIN_LIFT, FIN_HELD, LIFT_H * (1 - (1 - t) * (1 - t)),
              banner="  KUSTI!  ")
    for _ in range(2):
        frame(FIN_LIFT, FIN_HELD, LIFT_H, banner="  KUSTI!  ", dt=0.05)
    # slam down
    for i in range(1, 5):
        t = i / 4
        frame(FIN_SLAM, FIN_HELD, LIFT_H * (1 - t * t), dt=0.028)
    # impact
    spawn_burst(particles, cx, gy - 1, direction=face, blood=True)
    for i in range(7):
        frame(FIN_SLAM, FIN_SPLAT, 0, banner="  SLAM!  ",
              shake=2.4 * (1 - i / 7), dt=0.04)


# --- Main loop ------------------------------------------------------------

def choose_difficulty(stdscr):
    """Blocking menu — returns a DIFFICULTY key. Arrows/1-3 to pick, enter to start."""
    items = ["EASY", "MEDIUM", "HARD"]
    blurb = {
        "EASY":   "slow reflexes, whiffs defense, hesitates, hits soft",
        "MEDIUM": "solid reads, punishes some openings — a fair fight",
        "HARD":   "instant reactions, punishes everything, full damage",
    }
    sel = 1
    cyan = curses.color_pair(3)
    stdscr.nodelay(False)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        title = "NINJA-CLI"
        stdscr.addstr(max(1, h // 2 - 5), max(0, (w - len(title)) // 2),
                      title, curses.A_BOLD | cyan)
        prompt = "select difficulty"
        stdscr.addstr(max(2, h // 2 - 3), max(0, (w - len(prompt)) // 2),
                      prompt, curses.A_DIM)
        for i, name in enumerate(items):
            label = f"{i + 1}. {name}"
            desc = blurb[name]
            row = h // 2 - 1 + i * 2
            attr = (curses.A_BOLD | curses.A_REVERSE) if i == sel else curses.A_BOLD
            x = max(0, (w - 40) // 2)
            stdscr.addstr(row, x, f"  {label:<10}", attr)
            stdscr.addstr(row, x + 14, desc[: w - x - 16], curses.A_DIM)
        foot = "↑/↓ or 1-3 to choose · enter/space to fight · q quit"
        stdscr.addstr(min(h - 1, h // 2 + 6), max(0, (w - len(foot)) // 2),
                      foot, curses.A_DIM)
        stdscr.refresh()
        c = stdscr.getch()
        if c in (ord("q"), 27):
            return None
        elif c in (ord("w"), curses.KEY_UP):
            sel = (sel - 1) % len(items)
        elif c in (ord("s"), curses.KEY_DOWN):
            sel = (sel + 1) % len(items)
        elif c in (ord("1"), ord("2"), ord("3")):
            return items[c - ord("1")]
        elif c in (ord("\n"), curses.KEY_ENTER, ord(" ")):
            return items[sel]


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

    diff_name = choose_difficulty(stdscr)
    if diff_name is None:
        return
    diff = DIFFICULTY[diff_name]
    stdscr.nodelay(True)

    left_wall = ARENA_MIN
    right_wall = w - 6
    ground_y = h - 4

    player = Fighter(x=w // 3, facing=1, name="P1")
    ai = Fighter(x=2 * w // 3, facing=-1, name="AI", is_ai=True)
    ai.dmg_scale = diff["dmg"]

    # countdown
    for n in ("3", "2", "1", "FIGHT!"):
        draw(stdscr, player, ai, ground_y, msg=f"  {diff_name} — {n}  ")
        time.sleep(0.5)

    winner = None
    particles = []
    popups = []
    gt = 0.0                        # game clock — pauses during hit-stop
    hitstop_until = 0.0             # real-time end of the current freeze
    shake_mag = 0.0                 # current screen-shake magnitude (decays)
    last_real = time.perf_counter()

    while winner is None:
        real_now = time.perf_counter()
        real_dt = real_now - last_real
        last_real = real_now

        # hit-stop freezes the sim (fighters + particles) but not shake/input
        in_hitstop = real_now < hitstop_until
        dt = 0.0 if in_hitstop else real_dt
        gt += dt

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
                player.apply_move(-1)
            elif c in (ord("d"), curses.KEY_RIGHT):
                player.apply_move(1)
            elif c in (ord("w"), curses.KEY_UP):
                player.start_jump(gt)
            elif c in (ord("s"), curses.KEY_DOWN):
                held_crouch = True
            elif c == ord("j"):
                player.start_attack("punch", gt)
            elif c == ord("k"):
                player.start_attack("kick", gt)
            elif c == ord("g"):
                player.start_attack("grab", gt)
            elif c in (ord(" "), ord("l")):
                held_block = True

        # crouch/block are momentary holds; can't do either mid-swing or mid-air
        player.crouching = held_crouch and not player.busy() and not player.airborne
        player.blocking = held_block and not player.busy() and not player.airborne \
            and not player.crouching and player.stamina > 0
        if player.blocking:
            player.spend(BLOCK_DRAIN * dt)
            if player.stamina <= 0:
                player.blocking = False

        # keep player facing the AI (when grounded)
        if not player.airborne:
            player.facing = 1 if ai.x > player.x else -1

        # --- AI ---
        ai_think(ai, player, gt, left_wall, right_wall, diff)
        if ai.blocking:
            ai.spend(BLOCK_DRAIN * dt)
            if ai.stamina <= 0:
                ai.blocking = False

        # stamp when each guard was raised — this drives the parry window
        for f in (player, ai):
            if f.blocking and not f.was_blocking:
                f.block_start = gt
            f.was_blocking = f.blocking

        # --- state machines ---
        player.update_state(gt)
        ai.update_state(gt)
        player.update_vertical(dt)
        ai.update_vertical(dt)

        # --- physics: integrate movement, then separate overlapping bodies ---
        player.integrate_horizontal(dt, left_wall, right_wall)
        ai.integrate_horizontal(dt, left_wall, right_wall)
        resolve_collision(player, ai, left_wall, right_wall)

        # --- stamina regen ---
        player.regen(dt)
        ai.regen(dt)

        # --- grab / throw resolution (before strikes) ---
        for atk, foe in ((player, ai), (ai, player)):
            if atk.attack == "grab" and atk.state == "active" and not atk.has_hit:
                atk.has_hit = True
                if grab_connects(atk, foe):
                    before = foe.hp
                    kb = atk.facing * ATTACKS["grab"]["knockback"]
                    foe.take_hit(ATTACKS["grab"]["damage"] * atk.dmg_scale, gt, kb)
                    if foe.hp <= 0:
                        # lethal grab -> let the win check run the KO finisher
                        atk.state = "recovery"
                        atk.state_until = gt + ATTACKS["grab"]["recovery"]
                    else:
                        # non-lethal: quick in-arena slam, then floor the foe
                        play_throw(stdscr, atk, foe, ground_y, player, ai)
                        foe.state = "hitstun"
                        foe.state_until = gt + GRAB_KNOCKDOWN
                        atk.state = "recovery"
                        atk.state_until = gt + ATTACKS["grab"]["recovery"]
                        last_real = time.perf_counter()   # swallow the anim time

        # --- combat ---
        hs, sh = resolve_hits(player, ai, gt, particles, ground_y, popups)
        if hs > 0:
            hitstop_until = real_now + hs
        if sh > shake_mag:
            shake_mag = sh

        # --- particles + damage popups (frozen during hit-stop) ---
        for p in particles:
            p.update(dt)
        particles[:] = [p for p in particles if not p.dead(ground_y + 1)]
        for d in popups:
            d.update(dt)
        popups[:] = [d for d in popups if not d.dead()]

        # --- screen shake decay (real time, so it shakes during the freeze) ---
        shake_mag = max(0.0, shake_mag - SHAKE_DECAY * real_dt)
        if shake_mag > 0.2:
            sx = random.randint(-1, 1) if shake_mag > 0.5 else 0
            sy = random.randint(-1, 1) if shake_mag > 1.2 else 0
            shake = (sy, sx)
        else:
            shake = (0, 0)

        # --- win check ---
        if player.hp <= 0 and ai.hp <= 0:
            winner = "DRAW"
        elif ai.hp <= 0:
            winner = "P1 WINS!"
        elif player.hp <= 0:
            winner = "AI WINS!"

        draw(stdscr, player, ai, ground_y, particles=particles, popups=popups,
             shake=shake, now=gt)

        # --- frame pacing ---
        elapsed = time.perf_counter() - real_now
        if elapsed < FRAME:
            time.sleep(FRAME - elapsed)

    # --- finisher: the kusti slam (only on a decisive KO, not a double-KO) ---
    stdscr.nodelay(False)
    if winner == "P1 WINS!":
        play_finisher(stdscr, player, ai, ground_y)
    elif winner == "AI WINS!":
        play_finisher(stdscr, ai, player, ground_y)

    # end screen — wait for ENTER (q/esc also exits)
    draw(stdscr, player, ai, ground_y, msg=f"  {winner}  —  press ENTER  ")
    while True:
        k = stdscr.getch()
        if k in (ord("\n"), curses.KEY_ENTER, 10, 13, ord("q"), 27):
            break


def main():
    try:
        curses.wrapper(game)
    except KeyboardInterrupt:
        pass
    print("Thanks for playing Ninja-CLI!")


if __name__ == "__main__":
    main()
