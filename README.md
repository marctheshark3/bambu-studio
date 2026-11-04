# Bambu Studio

Agent skill for building one unsliced multi-plate project in Bambu Studio.

It measures meshes, assigns plates, and calls the installed `bambu-studio`
CLI. It does not design the part and it does not start a print. Part design
and process cards stay in the printables skills. Printer status, upload, and
confirmed start stay in `bambu-p1s-mcp`.

```sh
python3 -m unittest discover -s tests -v
```

The skill package is `skills/bambu-studio`. Tests use the Python standard
library only. They do not launch Studio or contact a printer.
