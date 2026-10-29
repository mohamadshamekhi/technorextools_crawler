# CLAUDE.md

Crawler for pumaair.ir that imports into the Technorex API. Python 3 standard library only.

- **Every script or user-facing flag is runnable from the panel.** When you add or change a script, add/update
  its step in `panel_steps.py` in the same change: in the right feature group (new feature → new group), in the
  order it must run, Persian `title`/`desc`, `token: True` if it calls the API, `danger: True` if it deletes,
  `optional: True` if it isn't part of the group's normal run. `panel.py` runs only what is listed there.
- Scripts that call the API read `ABZAR_TOKEN` and accept `--base` (default `https://api.technorextools.com`);
  never print the token.
- Keep `README.md` in sync with the commands.
