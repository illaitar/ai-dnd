# Maps

The world is procedurally generated and **deterministic** — the same seed reproduces the
same map. Towns are laid out Watabou-style (Voronoi wards, walls, a river, key buildings).
The model only adds flavor (names, descriptions) — never the layout.

**Towns** — four seeds:

![Generated town maps](assets/city_maps.png)

Regenerate the collage from the in-browser city generator: open `/city` (the collage page
renders seeds 7 · 42 · 1337 · 2024), then stitch the exported frames with
`python scripts/gen_map_collages.py city frame0.png frame1.png …` (see the script
docstring).

> Dungeon maps are temporarily omitted while the dungeon generator is being reworked.
