# Studio CLI contract

Use this file when building or checking a Bambu Studio command. The installed
`bambu-studio --help` remains the version check. Do not invent flags.

## Unsliced multi-plate export

Studio reads plate membership from an assemble list. That flag cannot be
combined with model arguments or with transform flags. `--orient`, `--arrange`,
`--rotate`, `--rotate-x`, `--rotate-y`, and `--scale` are transforms. Omit them.

```text
bambu-studio \
  --load-settings machine.json;process.json \
  --load-filaments filament.json \
  --load-assemble-list assemble-list.json \
  --export-3mf project.3mf \
  --outputdir out
```

Do not add `--slice`. A review project has no G-code. `plan_project.py argv`
builds this command and refuses the forbidden flags.

The assemble list is JSON with a `plates` array. Each plate needs `plate_name`,
`need_arrange`, and a non-empty `objects` array. Each object needs `path`,
`count`, and `filaments`. Optional `pos_x`, `pos_y`, and `pos_z` are mesh
translations, one number per copy. Paths must already exist. This Studio path
accepts STL and OBJ, not a 3MF as an object path.

Keep `need_arrange` false. The planner's positions are the placement. Studio
arrange can move or rotate a part after the fit check. Keep `count` at 1 and
do not set `assemble_index` for independently printed parts. The optional material
workflow deliberately uses a shared non-zero index to preserve material regions
as native parts of one printed body; do not independently repack those regions.

`filaments` uses Studio's 1-based filament slot. A one-material review uses
`[1]`. Pass the machine, process, and filament JSON for the named printer.
Those files stay on the machine. Do not copy them into a repository.

## Open and proof

Open the exported project alone:

```text
bambu-studio project.3mf
```

Write the plate images without focusing a window:

```text
bambu-studio --export-png 0 --outputdir proof project.3mf
```

`--export-png 0` means every plate. Do not add `--slice` to either command.

## After export

`plan_project.py check-3mf` must see a zip with `3D/3dmodel.model` and no
`.gcode` member. If the plate count differs from `plan.json`, stop. Do not
repair `Metadata/model_settings.config` by hand.

A PNG that shows the wrong bed face, an overlap, or a part off the bed is a
stop. Do not scale the mesh and do not flip X or Y to force a fit.

## Window inventory

Read window ids and titles. Do not activate, raise, close, or click them.
A title containing `Send print job` is protected. `studio_windows.py` always
returns empty `close` and `click` lists. Leave that dialog for the user.

## Printer handoff

Uploading, slicing to G-code, and starting a job belong to the sibling
`bambu-p1s-mcp` tools. Write tools there require confirmation. This package
does not store a printer address or login secret.

## Multiple project filaments

Repeat `--filament` on `plan_project.py argv` in logical filament order. The
script joins the paths for Studio's `--load-filaments` argument. These project
filament numbers do not identify the currently loaded physical AMS slots.

Studio combines `--export-3mf` with `--outputdir`, so the generated export argv
uses the 3MF basename. A specified 3MF parent must equal the output directory.
`check-3mf` requires printable geometry as well as a build item; a success exit
or a ZIP header alone does not establish that a project contains its models.
