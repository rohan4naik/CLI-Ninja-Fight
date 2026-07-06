# CLI-Ninja-Fight

Terminal 1v1 fighting game. Punch, kick, block. Player vs AI. Shadow-Fight style, ASCII.

## Run
```
python3 ninja.py
```
No dependencies — Python 3 stdlib `curses` only (built in on macOS/Linux).

## Controls
| key | action |
|-----|--------|
| `a` / `d` | move left / right |
| `w` / ↑ | jump — dodges low attacks (kicks); air-control move |
| `s` / ↓ | crouch (hold) — dodges high attacks (punches) |
| `j` | punch — fast, short range, 8 dmg, **high** |
| `k` | kick — slow, long range, 16 dmg, **low** |
| `space` / `l` | block — cuts 80% incoming damage |
| `q` | quit |

## Rules
- 100 HP each. First to drop the other wins.
- Getting hit staggers you (hitstun) and cancels your swing / jump — spacing matters.
- Kicks out-range punches but recover slower. Blocking leaves you unable to attack.
- **Height mind-game:** punches hit high → *crouch under them*. Kicks hit low → *jump over them*.
  You can't attack while airborne or crouched, so every dodge is a commitment.
- **Impact FX:** clean hits spray red blood particles; blocked hits throw pale sparks.
  Particles arc outward in the hit direction and fall under gravity.
- **Damage numbers:** the damage dealt floats up from each impact and fades —
  bold red for clean hits, dimmed `-N` for chip damage through a block.
