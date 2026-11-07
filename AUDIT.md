# Audit: renders against the game's sprites

Every unit was rendered from its recreation (`python -m wbrender.render all`) and compared with the
game's own pictures (`python -m wbrender.audit`): the outline match (IoU) of each map direction, the
portrait's outline score, and a colour error. `out/audit/<unit>.png` shows each unit's pictures,
the game's above, the render's below.

Low scores have three causes, and only the first is the renderer's to fix:

1. **The renderer** (camera, light, palette).
2. **The recreation differs from the game's model**, in pose or build. No camera or light makes the
   two agree, and such a unit is no reference for measuring the light.
3. **The game drew the picture otherwise** than its model would render (a turned sprite, a portrait
   of another build).

## The camera

Every well-matched unit's four map directions are turned square, within a few degrees of
0/90/180/270. The game's renders were made square to the axes. A unit fitting to odd turns
(the trex: left 233, down 309) is a recreation posed unlike the game's, not a camera to copy.
`python -m wbrender.fit UNIT --axes` fits with the turns held square.

## Findings by unit

| Unit | Map | Portrait | Cause and notes |
|---|---|---|---|
| dirtbuggy | 0.86 | 0.90 | Outline good. The game's map sprite has green lights at the corners, which the recreation lacks. In the portrait, the game's cab is trans-yellow over grey studs and its grille shows white teeth; the recreation's front lights render as round white clusters. (2) |
| buggy, dozer, dumptruck, house, nursery, garage, gas station | ≥ 0.90 | ≥ 0.86 | Good. The gas station's and the marina's tiled bases are studded plates in the game (replaced in `config/units.json`, `replace_parts`). |
| duck, frog, snail, fish | 0.76 to 0.83 (water directions lowest) | ≥ 0.80 | Good on land. The waterline cuts are a little off on the water directions. These four, buggy, dirtbuggy, dozer and dumptruck are the portrait light's references (`heroshade.references()`). |
| defender | 0.68 | 0.46 | The recreation is squatter than the game's build, and its head differs. Portrait camera pinned by eye: from a little below, the front to the left. (2) |
| treebot | 0.63 | 0.41 | The arms are posed otherwise; the game's portrait shows a trans-cyan cockpit that renders dark here. (2) |
| freezebot | 0.39 | 0.36 | The recreation holds its gun raised; the game's holds it level. (2) Tan rendered too pale (palette, fixed: see below). |
| trex | 0.29 | (none) | The recreation's spine is level with the tail held straight out; the game's stands upright with the tail sloping to the ground. (2) |
| shark | 0.26 (up, down) | (none) | Left and right match well. The game's up and down sprites are drawn diagonally, the shark turned about 45 degrees, unlike every other unit. (3) Its colours: the game's shark is light blue all over. |
| steamshovel | 0.70 | 0.59 | The game's portrait shows the bucket raised high; the recreation's is lowered, so the fitted portrait camera looks into the bucket. (2) |
| repairbot | 0.70 | 0.61 | Map sprites rendered a little small. (1, 2) |
| lion | 0.70 | 0.63 | Tan and brown rendered pale (palette, fixed: see below). The game's "portrait" is a map-like side view. |
| scorpion, crab, watercrab | 0.68 to 0.70 | (none) | Legs posed otherwise. The water crab's game sprites are a deeper blue. (2) |
| freighter | 0.69 | 0.73 | Up and down narrow. The game's portrait is the tugboat's. (3) |
| bluebird, cargo copter | 0.57, 0.47 | (none) | Compared against one right-facing sprite of each of unknown origin (not from the game's files). Not a measure of the renderer. |
| windmill | (none) | 0.71 | No map sprite in the game to compare. |

## The map sprites' light

The map sprites were first composited from a few Cycles sun passes with a palette learned from the
game's sprites (`wbrender/shade.py`). That fit overexposed flat tops: a medium-blue top clipped to
near white, and the renders ran about 21 levels brighter than the game's on average.

They are now lit as the portraits are (`wbrender/mapnormal.py`): each unit's sprites are rendered from
its fitted map camera as colour ids, the sky's light and each pixel's surface direction, laid on the
game's sprites, and a light rig is fitted face by face over fourteen units at once, the palette
solved alongside, every channel clipped. As with the portraits, each unit's sprites have their own
exposure (the duck's yellow is lemon, the dump truck's ochre); a new unit takes the middle one.

On the faces it was fitted on, the rig comes to an error of 26.1, against 31.6 for flat light and
37.2 for the sprites made before. Per unit, the mean colour error against the game's sprites fell
from 53.7 to 46.5 (duck), 69.5 to 55.4 (buggy), 112.0 to 88.0 (defender), 80.9 to 56.3 (fish) and
81.9 to 58.6 (dump truck).

Medium blue (LDraw 73) is learned from the robots built in it (the defender, repairbot, treebot,
crab), not from the marina, whose cyan parts taught it as cyan. A colour learned late that strays
far from what the LDraw colour map predicts is otherwise dropped as a model mismatch.

## The palette

The first world palette was learned from the eight best-matched units and held eleven colours.
Every other colour (tan, brown, the greens, the trans colours) fell back to LDraw's own, which
renders paler and greyer than the game's. `python -m wbrender.shade colours` learns the rest from
every unit's sprites, with the light held as fitted. It also fits a map from LDraw's colours to the
game's for colours no sprite shows.

## The portraits' light, as measured

The portraits' lighting and finish were measured on the game's own portraits of units whose builds
match JappaWakka's models. Each render is registered onto the game's portrait to the pixel, its
camera fitted on the inside of the picture, roll included (`wbrender/herocam.py`), and compared
face by face (`wbrender/heronormal.py`). Findings:

- **Each portrait was lit on its own.** A rig fitted on one portrait alone matches about twice as
  well as any rig shared across them: the buggy 9.5 against 18.4, the dirtbuggy 12.2, the duck 5.4.
  The family resemblance is two low lights, near the horizon, from either side and a little behind,
  their balance varying. That is why tops read darker than sides.
- **Hard cast shadows.** Faces turned to a light but behind something are half as bright and less.
  Shadows improve every portrait's fit: the fish 8.3 against 20.3 without, the snail 14.1 against
  21.1, the duck 5.4 against 8.1.
- **Reflective plastic.** The plastic mirrors the model's other parts and its surroundings: the
  fish's jaw top mirrors the head above it. Fitted together with each portrait's lights, the
  portraits agree on reflectivity around 10–25% face on, rising toward the edges, in a studio with a
  **dark sky above and a bright floor below**. That is the other half of why tops read darker than
  sides. Each rig's reflections improve its fit markedly: the duck 22.5 to 11.2, the fish 17.2 to
  12.1, the dump truck 33.1 to 22.6 (pixel error). The reflection pass (`reflect_pass` in
  `blender/wbsprite.py`) records which part, or which direction of the world, each pixel reflects;
  the compositor mixes in that part's colour or the fitted sky and floor.
- **Overexposed, each channel clipped on its own.** A yellow's red is 255 on every face, lit or
  shaded; only its green carries the light. That turns a shaded yellow orange and keeps a lit one
  lemon.
- **Each portrait at its own exposure**, as part of its own rig.
- **Slopes darker than smooth faces.** LEGO slopes are grained and matte on top.
- **Glass** greys and dims what is behind it (the buggy's red seat reads near grey through the
  windscreen), adds its own grey, and carries sharp reflections: the white streaks.
- **Shine on the tyres' rubber only**: tight highlights on the tread edges.
- **Kept as JPEG.** The white around each portrait rings with compression noise. Quality 40,
  without chroma subsampling.

How the renderer uses this:
- **A unit the game has a portrait of** is lit by the rig fitted on that portrait, with that
  portrait's colours.
- **A new unit** borrows the rig of the most similar portrait (`hero_rig_from` in
  `config/units.json`: the bluebird the duck's, the cargo copter the buggy's). Its colours are each
  colour's median across the fitted portraits, brought to the same scale. Black, the greys and white
  come from the world palette instead: JappaWakka's builds put black where the game's have grey, and
  the references' whites are mostly shaded.

Consistent portraits (each rendered from the map's own model) borrow the camera and the rig of the
game's portrait they stand for. The dirtbuggy's map model is the buggy's portrait build in yellow,
so the buggy's portrait is the reference for it (`consistent_like`). The freighter's game portrait
is the tugboat's (`hero_as`). A borrowed rig takes the lender's exposure, matched to the model's
median light, and the lender's colours; any other colour comes from the world palette at the
lender's scale.

A consistent portrait keeps the borrowed camera's turn and height but not a lens shorter than
30 mm: the tugboat's portrait was fitted near 20 mm, which stretches the long freighter out of shape.

A colour the lender never fitted (the buggy has no real yellow, only its headlights) is carried
over by ratio: from each portrait that fitted both it and one of the lender's colours, as so many
times that colour. The game's yellows are lit far brighter than its reds and clip to lemon; scaled
as a whole, the dirtbuggy's yellow came out khaki and then golden. A ratio that leaves the colour's
hue, or comes through a colour fitted past full brightness, is not used.

## Glass and rubber

- **Glass** mirrors its surroundings as well as showing what is behind it: the white bands across
  the buggy's canopy and the dirtbuggy's windscreen. Fitted on those two windscreens, its
  brightness spread now tracks the game's (the dirtbuggy's: game 32/81/108/150/225/248 at the
  10th to 97th percentiles, render 55/72/107/150/225/250).
- **Rubber** is matte: no mirror in it, or a tyre's underside catches the bright floor in white
  specks. Its own tight highlights and rim light (raised to 0.9 for the buggy's white rims) stay.

## The tugboat

The game's tugboat portrait is blue, highly lit and reflective on the right of its hull. Its red and
black bricks are stouter than real LEGO bricks, so no recreation lines up with it exactly. Its
camera fitted to a 10 mm lens to make up for that; it is now held to 18 mm or longer and fitted
again, and its rig refitted with reflections, the world reflected grey (unconstrained, it fitted a
pink sky).

## Posing

Some recreations are posed otherwise than the game's renders. `pose` in `config/units.json` turns a
part or submodel of the main file about a pivot. `python -m wbrender.posefit` searches a joint's
angle against the map sprites, or with `--hero` against the portrait.
- **Robot lab:** the rooftop panel and dish turned −45° on its pin (fitted on the portrait).
- **Freezebot:** its gun turned 75° (outline match 0.37 → 0.44 with the camera refitted). Its arms
  and legs are posed otherwise too and still need doing. Its portrait in the game is a reused promo
  render from the Robo Platoon set, so it is no reference for the portrait.

