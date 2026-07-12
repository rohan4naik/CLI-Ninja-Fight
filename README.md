<div align="center">

# 🥷 CLI-Ninja-Fight

**A real-time 1v1 fighting game for your terminal.**

Punch, kick, grab, and parry your way past a reactive AI opponent. Every blow lands
with knockback, freeze-frames, and screen shake for real fighting-game weight — all
in crisp ASCII.

`macOS · Linux · WSL`

</div>

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Install & Play](#install--play)
- [Controls](#controls)
- [How to Play](#how-to-play)
- [Difficulty](#difficulty)
- [Strategy Tips](#strategy-tips)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Features

- **Real-time combat** — no turns, no menus mid-fight. Pure reflex and reads.
- **Height mind-game** — punches strike high, kicks strike low. Duck or hop the
  wrong guess.
- **Deep defense** — a held guard is a spectrum: **parry** a perfectly-timed block,
  **chip** through a steady one, or **shatter** a guard that runs out of stamina.
- **The throw triangle** — strikes beat jumpers, a grab beats a blocker, a jump
  escapes the grab. Turtling is never safe.
- **Stamina economy** — every attack, jump, and block spends stamina. Overcommit
  and you're left wide open.
- **Impact feedback** — knockback, freeze-frames, screen shake, particles, and
  floating damage numbers sell every hit.
- **Cinematic KO finisher** — close out a round with a slow-motion overhead slam.
- **Three difficulty tiers** — from a forgiving warm-up to a merciless
  read-everything opponent.

---

## Requirements

| | |
|---|---|
| **Python** | 3.7 or newer, available on your `PATH` |
| **OS** | macOS, Linux, or Windows via **WSL** |
| **Terminal** | minimum **50 × 12** characters; color recommended |

---

## Install & Play

### Via npm (recommended)

```bash
# play instantly, no install
npx cli-ninja-fight

# or install the `ninja` command globally
npm install -g cli-ninja-fight
ninja
```

Pick a difficulty on the start screen and fight.

> **Note:** the game requires Python 3 on your `PATH`. The launcher checks for it
> and tells you exactly what to install if it's missing.

---

## Controls

| Key | Action |
|-----|--------|
| `A` / `←` | Move left |
| `D` / `→` | Move right |
| `W` / `↑` | Jump — clears low attacks |
| `S` / `↓` | Crouch *(hold)* — ducks high attacks |
| `J` | Punch — fast, light, strikes **high** |
| `K` | Kick — slower, heavy, strikes **low** |
| `G` | Grab — a throw that beats a block *(but whiffs if they jump)* |
| `Space` / `L` | Block *(hold)* — soaks most damage; **time it to the hit for a PARRY** |
| `Q` / `Esc` | Quit |

Punch and kick have the **same range** — they differ in speed, power, and height,
not reach. Movement carries momentum: tap to build speed, release to glide to a halt.

---

## How to Play

Two fighters start with full health. **Drop your opponent's health to zero to win.**

**The core loop is a mix-up between three ideas:**

1. **Height** — a punch sails over a crouch; a kick passes under a jump. Guess the
   incoming attack and dodge on the correct axis. You **can't** attack while
   airborne or crouched, so every dodge is a commitment.
2. **The throw triangle** — strikes beat jumpers, a **grab** beats a blocker, and a
   **jump** escapes the grab. Turtling behind block is never safe.
3. **Resources** — blocking bleeds off damage but drains stamina and locks you out
   of attacking. Every swing, hop, and throw costs stamina too, so reckless offense
   leaves you empty and open.

**Blocking has depth — a held guard is a spectrum, not an on/off switch:**

- **Parry** — raise your guard *just* as the blow lands and you take **zero damage**,
  refund stamina, and freeze the attacker wide open for a free punish. The parried
  ninja flashes green.
- **Block** — hold a steady guard with stamina in the tank: most of the damage is
  soaked, but **chip** still leaks through, each hit costs stamina, and you're
  briefly locked out of countering.
- **Guard break** — block on an empty tank and your guard **shatters**: real damage
  plus a long, fully-punishable stun. Turtling on fumes gets you killed.

The opponent reads for parries too — the harder the difficulty, the more often it
will bait your swing and catch it clean.

> Land a grab and your ninja hoists the opponent overhead for a heavy slam and a
> hard knockdown. Miss, and the long recovery is a free punish.

Landing a clean hit staggers your opponent, cancels whatever they were doing, and
knocks them back. Get hit yourself and the same happens to you — so whiffing an
attack in someone's face is a fast way to eat a punish.

Watch the two bars for each fighter: **HP** (top) and **SP / stamina** (below it).

---

## Difficulty

Choose on the start screen with `↑`/`↓` or `1`–`3`, confirm with `Enter`.

| Tier | Feel |
|------|------|
| **Easy** | A patient sparring partner. Slow to react and prone to mistakes — good for learning the mix-ups. |
| **Medium** | A fair, honest fight. Reads your spacing and punishes sloppy play. |
| **Hard** | Ruthless. Near-instant reactions, punishes nearly every mistake, and hits at full strength. |

---

## Strategy Tips

- **Bait, don't rush.** Hover just outside kick range and let the opponent
  overextend, then punish the recovery.
- **Mix your heights.** Predictable punch/kick patterns get read and dodged. Vary
  high and low.
- **Respect your stamina.** Keep enough in reserve to block or dodge — running dry
  in the danger zone loses rounds.
- **Blocking isn't free.** It saves HP but costs stamina and tempo; use it to
  weather a flurry, not as a resting state — a **grab** will punish a held block.
- **Grab on read, not on hope.** The throw is slow to start; use it when you expect
  a block, and jump if you read one coming at you.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Python 3 is required…` | Install Python 3 and make sure `python3` is on your `PATH`. |
| `Terminal too small…` | Resize the window to at least **50 × 12** and relaunch. |
| Garbled or no colors | Use a color-capable terminal; check `$TERM` (e.g. `xterm-256color`). |
| Won't start on Windows | Run inside **WSL** — a native Windows terminal isn't supported. |
| Input feels laggy | Avoid running over a slow/high-latency SSH session. |

Quit any time with `Q` or `Esc`.

---

## License

MIT — see [LICENSE](LICENSE).

<div align="center">

*Built for the terminal. No GPU required — just reflexes.*

</div>
