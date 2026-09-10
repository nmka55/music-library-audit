"""Interactive local setup: one XML export and any number of read-only roots."""

from pathlib import Path
from config import resolve_path, save, validate


def configure(c, ask=input, tell=print):
    c = dict(c)
    workspace = Path(c["_workspace"])
    tell("Choose your exported library XML and read-only music folders.")
    tell("Relative paths are resolved from the workspace: " + str(workspace))
    while True:
        raw = ask(f"Library XML [{c['apple_music_xml']}]: ").strip().strip('"').strip("'")
        path = resolve_path(raw or c["apple_music_xml"], workspace)
        if path.is_file():
            c["apple_music_xml"] = str(path)
            break
        tell("That XML file does not exist. Enter an existing file path.")
    roots = []
    tell("Add one folder at a time. Enter done (That's all) when finished.")
    tell("This replaces the saved folder list; enter every folder you want included.")
    while True:
        raw = ask(f"Music folder {len(roots) + 1}, or done (That's all): ").strip()
        if raw.casefold() in ("done", "that's all", "thats all", "all", ""):
            if roots:
                break
            tell("Add at least one music folder before selecting That's all.")
            continue
        path = resolve_path(raw.strip('"').strip("'"), workspace)
        if not path.is_dir():
            tell("That folder does not exist. Try again.")
            continue
        if str(path) in roots:
            tell("That folder is already included.")
            continue
        trial = dict(c, offline_music_roots=roots + [str(path)])
        try:
            validate(trial)
        except ValueError as error:
            tell(str(error))
            continue
        roots.append(str(path))
        tell(f"Added folder {len(roots)}.")
    c["offline_music_roots"] = roots
    save(c)
    tell("Saved local settings. Future runs reuse these paths; --setup changes them.")
    return c
