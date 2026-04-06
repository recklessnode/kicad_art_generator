# Conversation Log

## 2026-04-05

- Created the private `kicad_art_generator` repository and bootstrapped a Linux-first WSL workflow.
- Added the initial CLI for SVG and raster to KiCad footprint generation.
- Logged the Ubuntu and WSL prerequisites in the setup script and README.
- Extended the workflow to match the original goal: two-color PNG processing with yellow mapped to copper, white mapped to silkscreen, combined into a single reusable footprint, with 1 inch, 2 inch, and 4 inch preset generation.
- Added a simpler single-layer raster workflow with explicit foreground and background color matching, plus green-board preview PNG output.
- Validated the real `cholla_cactus.png` asset as black art on `F.SilkS` while ignoring the white background.
- Extended sizing so output generation is explicitly parametric for custom batch sizes in either inches or millimeters, not just the default preset-size workflow.
- Added named art presets for silkscreen, exposed copper, covered copper, and exposed substrate tones, including mask-opening behavior where needed.
- Added dual-color preview generation and validated the `Cholla Energy.png` logo as exposed ENIG-style yellow copper plus green silkscreen.
- Added direct `.pretty` export support so generated footprints can be written straight into a KiCad footprint library.
- Improved dual-color extraction so it absorbs adjacent shades around the primary colors, fixing missing darker-green text in the Cholla logo workflow.
