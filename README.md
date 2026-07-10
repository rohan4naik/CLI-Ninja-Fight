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
| `a` / `d` | move left / right — momentum-based (tap to accelerate, glide to stop) |
| `w` / ↑ | jump — real gravity arc; dodges low attacks (kicks); limited air-control |
| `s` / ↓ | crouch (hold) — dodges high attacks (punches) |
| `j` | punch — fast, short range, 8 dmg, **high**, 10 stamina |
| `k` | kick — slow, long range, 16 dmg, **low**, 22 stamina |
| `space` / `l` | block — cuts 80% incoming damage; drains stamina while held |
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
- **Weighty motion:** fighters carry momentum — accelerate, glide, and shove each
  other apart on contact. Knockback flings you back along the hit direction; kicks
  hit far harder than punches.
- **Stamina (`SP` bar):** every attack, jump, and held block burns stamina and it
  regenerates when you rest. Empty and you can't act — pace your offense.
- **Impact juice:** clean hits trigger brief freeze-frames (hit-stop) and screen
  shake, scaled to the blow — kicks bite harder than punches.
- **Smarter AI:** reads your spacing and sits at the tip of kick range, dodges by
  height, punishes whiffed recovery, baits with feints, and presses harder when
  it's losing.
