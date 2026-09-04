*[한국어](README.md) · **English***

# codestrata

Turn a git repository into a 3D **structure × time** landscape. The ground plane is file
structure, the vertical axis is time, and each bead is one file's change in one commit.

It shows you which files have always moved together, which periods churned, and what a file
you are about to touch tends to drag along with it. It renders in a browser — and **inside
your terminal**.

---

## Quick start

```bash
git clone https://github.com/Slangoij/codestrata.git
cd codestrata && bash install.sh          # installs three commands into ~/.local/bin
codestrata ~/your/repo                    # builds the HTML and prints the address
```

The installer tells you if `~/.local/bin` is not on your `PATH`.

## Three ways to look

| Command | What it does | When to use it |
|---|---|---|
| `codestrata <repo>` | Builds one self-contained HTML file and serves it | The default. Smoothest and most accurate |
| `codestrata-tui <repo-name>` | Streams a headless Chromium frame into terminal cells as pixels | When you don't want to leave the terminal |
| `codestrata-cli <repo>` | Draws the 3D scene with braille characters, no Chromium | On terminals that cannot display graphics |

```bash
codestrata                       # the repo the current directory belongs to
codestrata ~/repo-a ~/repo-b     # several at once
codestrata ~                     # not a repo? it finds every repo underneath and draws them all
codestrata <repo> --no-serve     # build the file, skip the server
codestrata <repo> --port 9000 --out ~/somewhere
```

Output lands in `~/debug-captures/codebase-3d/<repo>.html` as a single file with no
dependencies. An `index.html` in the same folder lists them, so you can open the address
without naming a file.

## Controls

Drag to rotate, wheel to zoom, `Shift`+drag or right-drag to pan. Click a commit or a file and
that node becomes the pivot; wheel zoom keeps the point under your cursor in place.

Everything also works from the keyboard — press `?` for help. On tablets and phones, one finger
rotates and two fingers pinch to zoom and pan.

In the terminal view (`codestrata-tui`), press `p` to toggle pan mode. Most terminals capture
`Shift`+drag for their own text selection and never pass it to the application. Press `q` to quit.

## What it was built for

It is aimed at people who live in a terminal, move between several repositories, and work over
ssh on remote machines. That is why the output is a single HTML file that opens without a
server, and why the scene can be drawn in a terminal on the far side of an ssh connection.

| | What you need |
|---|---|
| Everything | `git` and `python3` — **standard library only** |
| Browser view | Any browser with WebGL. three.js is loaded from a CDN |
| `codestrata-tui` | A terminal that speaks the kitty graphics protocol (kitty · Ghostty · WezTerm), `chromium`, and `allow-passthrough on` if you are inside tmux |
| `codestrata-cli` | Any terminal. Chromium is not needed |
| Optional | If the repository contains a code-dependency graph at `graphify-out/graph.json`, those edges are drawn too. Without it, the layout uses co-change history alone |

Developed and verified on Linux (Ubuntu 24.04 · Python 3.12 · Ghostty + tmux 3.4). GNU-only
flags were deliberately avoided with macOS in mind, but it has not actually been run there.
Windows is not a target.

## Environment variables

These affect the terminal view only. You will rarely need them.

| Variable | Default | What it does |
|---|---|---|
| `CODESTRATA_CELL` | auto-detected | Pixel size of one terminal cell, as `9x18`. Set it when your terminal does not answer the size query |
| `CODESTRATA_SS` | `1.0` | Pixel density. Raise it to `2` if the cell size cannot be detected and the image looks stretched |
| `CODESTRATA_PLACEMENT` | `auto` | `unicode` anchors the image to real cells so tmux pane borders are respected. `direct` is the older cursor-anchored placement |
| `CODESTRATA_TUI_LOG` | unset | Logs input and camera state to a file |

`codestrata-tui --probe` draws nothing and prints one line telling you what your terminal
answers for its cell size. Start there when text looks mangled.

## Verification

The scripts under `tools/` check behaviour by value, using a pseudo-terminal and a headless
browser. Run them after you change something.

```bash
python3 tools/cell-check.py          # the four cell-size detection paths
python3 tools/tui-check.py           # terminal view: frames, drag, wheel, cleanup
python3 tools/placement-check.py     # anchoring the image to cells
python3 tools/cli-check.py           # character view
python3 tools/orbit-check.py         # camera: pivot, pan, zoom, selection  (needs websocket-client)
```

## Limitations

Rendering is done in software, so the terminal view runs at 4–8 frames per second. A 3D scene
is a tool for reading shape and neighbourhood, not for comparing exact numbers. Very large
repositories take a while to draw, and when sweeping with `codestrata ~` any repository with
more than 5,000 commits is treated as a vendored tree and skipped.

Author names and email addresses are never extracted from the repository. The output contains
commit hashes, commit messages and file paths only.

## Feedback

If something is awkward or does not work, please write to **slangoij@gmail.com**. Telling me
which terminal and which operating system, what you were trying to do and what you got instead,
makes it much faster to reproduce. GitHub issues are welcome too.

## License

MIT. See `LICENSE`.
