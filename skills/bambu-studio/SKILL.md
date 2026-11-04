---
name: bambu-studio
description: "This skill should be used when the user asks to \"pull it up on bambu\", \"open in Bambu Studio\", \"one Studio project\", \"put these on plates\", or \"show me the plate\". It builds one unsliced multi-plate project with the Studio CLI. Not part design, not 3d-print-slice, and not a printer start."
version: 0.1.0
---

# Bambu Studio

Build one unsliced Bambu Studio project and open that one file. Measure the
meshes, assign plates, and let the Studio CLI write the 3MF. Show the plate
images from `--export-png`. Leave an existing Send print job dialog alone.

This skill does not design the part, write a process card, or start a print.

## When to invoke

Invoke it when the user asks to pull a model up on Bambu, put parts in one
Studio window, share a plate, or show the plates before printing.

Do not invoke it to design or validate a part. Those jobs belong to the
printables skills. Do not invoke it to write a process card or a one-body
3MF from `PRINT_SPEC.yaml`; that is `3d-print-slice`. Do not invoke it to
read printer status, upload, or start a job. That is `bambu-p1s-mcp`, and
its write tools stay behind confirmation.

A request to send, upload, or start the print ends this skill. Do not click
Send in a window that is already open.

## Workflow

1. Identify the meshes and the bed before opening Studio. Take the bed size
   from the named machine profile, not from a remembered plate. A Bambu P1S
   textured plate is 256 by 256 mm only when that profile is the selected
   machine. Keep the mesh's current bed face. Collect the machine, process,
   and filament JSON paths from the installed Studio system profiles. Do not
   copy those files into a repository and do not put a printer address or
   login secret in the plan.
2. Inventory Studio windows before launching anything. On X11, write one
   `id<TAB>title` line per window. Use `xdotool search --class BambuStudio`
   and `xdotool getwindowname` only. Do not call `windowactivate`,
   `windowraise`, `windowfocus`, `windowclose`, `key`, `click`, or
   `mousemove`. Pass that file to the window script:

   ```bash
   python3 scripts/studio_windows.py inventory --text windows.tsv
   ```

   A title containing `Send print job` is protected. The script's `close` and
   `click` lists stay empty. Quote the protected titles in the reply and leave
   them. If `xdotool` is missing, skip the inventory and still do not close,
   raise, or click any Studio window.
3. Plan the plates from this skill directory. Pass each requested group as
   `--part group=file.stl`. Repeat the group name for parts that should share
   a plate. Use `--allow-split` only when the user allowed a group to split,
   including a request such as "together if they fit." Omit it when the user
   said the parts must share a plate.

   ```bash
   python3 scripts/plan_project.py plan \
     --bed-x 256 --bed-y 256 --gap-mm 5 \
     --allow-split \
     --part fronts=stl/left_frame.stl \
     --part fronts=stl/right_frame.stl \
     --part backs=stl/left_lid.stl \
     --part backs=stl/right_lid.stl \
     --out studio-plan
   ```

   Replace the bed, gap, and paths. The default gap is 5 mm between bounding
   boxes. Raise it when the machine profile reserves a calibration strip. Do
   not shrink a mesh to recover that strip.
4. Read `studio-plan/plan.json` before exporting. Report every `splits`
   reason with the measured spans. A split means those parts do not share a
   plate. Do not scale the mesh. Do not rotate it about X or Y. Do not treat
   a hole, window, or open frame as empty packing space. The fit test is the
   bounding box. Z rotation is allowed only when the script sets
   `rotation_z_deg` to 90, and only about the bed axis. A `PLAN:` failure is
   the answer. Do not retry it by scaling, nesting, or editing the mesh.
5. Build the command with the argv subcommand. Pass the installed
   `bambu-studio` binary and the three profile JSON files. Those profiles
   stay outside this package.

   ```bash
   python3 scripts/plan_project.py argv \
     --slicer bambu-studio \
     --assemble studio-plan/assemble-list.json \
     --out-3mf studio-plan/project.3mf \
     --outputdir studio-plan \
     --machine machine.json \
     --process process.json \
     --filament filament.json
   ```

   Run the `export` array exactly. It uses `--load-assemble-list` and
   `--export-3mf`. It must not contain `--slice`, `--orient`, `--arrange`,
   `--rotate`, `--rotate-x`, `--rotate-y`, `--scale`, `--assemble`, or a
   model path beside the assemble list. Those flags either slice the project
   or are transforms that Studio rejects next to an assemble list. The field
   rules are in `references/studio-cli.md`.
6. If `bambu-studio` is missing, stop and name the missing executable. Do not
   rename an STL to `.3mf`. Do not clone an old project's
   `Metadata/model_settings.config`. Do not open one Studio process per STL
   while waiting for a project file.
7. Check the export before showing it:

   ```bash
   python3 scripts/plan_project.py check-3mf studio-plan/project.3mf
   ```

   A G-code member means the file was sliced. Delete that output and stop.
   The plate count must match `plan.json`. A mismatch is a stop. Do not repair
   the zip, and do not launch the GUI to drag parts onto plates.
8. Render every plate with the `proof` array from the argv output. Use those
   PNG files as the proof. Do not use a desktop screenshot as a substitute.
   Do not claim a plate is correct without the image or an explicit export
   failure. If the PNG shows the wrong bed face, an overlap, or a part off
   the printable area, stop and show that image. Do not flip the model to
   hide the result.
9. Open Studio with the `open` array: the binary and the exported project as
   its only argument. Launch one process. Do not pass the individual STLs.
   Do not click Arrange. Do not raise or click the protected send dialog.
   Tell the user the project path, the plate names, any split reasons, and
   that nothing was sent.
10. Stop. A later print still needs a confirmed `bambu-p1s-mcp` upload or
    start. This skill does not call those tools and does not confirm a print
    on the user's behalf.

## Reply

Name the exported project, each plate, and any split. Quote the measured
spans from `plan.json` when a requested group does not fit. Say that the
project is unsliced and that no print was sent. If a Send print job window
was already open, say that it was left untouched. Attach or link the proof
PNG for each plate. Do not describe a window layout as proof that the meshes
landed on those plates.

A two-frame example that fails a shared plate is a 140.7 by 162.6 mm frame
beside a 130.7 by 162.6 mm frame on a 256 mm bed. The short sides add to
271.4 mm before the gap, and every Z rotation still exceeds the bed. The plan
must split them. Do not spend the turn searching for a nested pose inside the
open centers unless the user explicitly asks for a footprint intersection
test. This skill does not provide that test.

## Pitfalls

Do not launch one Studio process per STL and then try to merge the windows.
That leaves stale projects next to the new plates and hides the send dialog.
Build the project file first, then open that file once.

Do not click through the Prepare or Arrange toolbar. The assemble list is the
plate assignment. A click can move a locked plate, accept a dialog, or send
the old job.

Do not pass `--slice`, even with plate 0, when the user asked to look. Slice
output is a printable `.gcode.3mf`. `check-3mf` rejects it. Slicing for a
confirmed print belongs to `bambu-p1s-mcp` after this review, not before it.

Do not reuse an older 3MF as a template and swap its mesh XML. The object
ids, plate ids, and transforms in that file belong to the old export. The
CLI assemble list is the supported way to create a new multi-plate project.

Do not mark the task done because a window title contains the part name. The
window can still hold the previous mesh. The proof is the PNG from the
exported project, plus `check-3mf` reporting no G-code.

## Placement rules

`need_arrange` stays false. The planner writes mesh translations into the
assemble list so Studio does not move the parts after the fit check. A 5 mm
gap is the default between bounding boxes. Raise it when the machine profile
reserves a calibration zone; do not silently shrink the part instead.

A single part that is larger than the bed on both Z rotations fails the plan.
Report that failure. Do not scale it down and do not cut it unless the user
asks for a separate split.

An exported PNG that shows the wrong bed face, an overlap, or a part off the
printable area ends the task. Do not flip the model to hide that result.

## Resources

- `scripts/plan_project.py` measures meshes, packs plates, writes the assemble
  list, and builds the unsliced export, open, and proof commands.
- `scripts/studio_windows.py` classifies an existing window list and refuses
  close or click actions.
- `references/studio-cli.md` records the assemble-list fields, the forbidden
  flags, and the printer handoff.

Resolve both scripts from this skill directory. Run `python3 -m unittest`
from the source repository after changing them. Those tests do not launch
Studio and do not talk to a printer.
