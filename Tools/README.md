# TNS modding tools

These are small scripts used for the Oct 2026 TNS audit. They need Python 3.10+ and, for the last one, Node 18+.

| Script | What it does | Run |
|---|---|---|
| `tns_audit.py` | Static checks. Covers brace balance, duplicate event/decision IDs, events called but never defined, missing localisation for countries, parties, decisions and events, UTF-8 files, and malformed CSV lines. | `python3 tns_audit.py path/to/struggle out_dir` → `out_dir/audit.txt` |
| `tns_profile.py` | Performance profile. Counts polled vs triggered-only events, loop scopes in triggers, unfiltered decisions, starting pops and leaking vanilla files. Needs `audit_lib.py` next to it. | `python3 tns_profile.py path/to/struggle path/to/Victoria\ 2 profile.json` |
| `victorian_tools_report.js` | Runs the Victorian Tools (TGExtension) language server headless and writes its full-mod report as JSON. | See below |

## Running Victorian Tools headless
```
git clone --depth 1 https://github.com/The-Grand-Combination/TGExtension tgext
cd tgext && npm ci --ignore-scripts && node esbuild.js && cd ..
node victorian_tools_report.js tgext path/to/repo-root report.json "C:/path/to/Victoria 2" "The Northern Struggle"
```
- `repo-root` is the folder holding `struggle.mod` next to `struggle/`.
- Pass the game path so vanilla pictures, flags and inventions count. Without it, those show up as false "missing" errors.

Both Python scripts treat every file as Windows-1252, as the game does.

## Map scripts (need numpy, pillow, scipy)
Run them in this order. Each later script uses the `labels.npy` the first one writes.
| Script | What it does |
|---|---|
| `positions_check.py mod_dir out_dir` | Checks every positions.txt point against provinces.bmp. Flags points outside their province, missing entries and duplicate blocks. |
| `positions_fix.py mod_dir out_dir [--fill-missing]` | Moves points more than 3 px outside their province back inside, removes empty duplicate blocks, and adds missing blocks. Only changed blocks are rewritten. |
| `adjacency_check.py mod_dir out_dir` | Checks for long-distance pixel links, wrap-edge links, bad adjacencies.csv rows and isolated land. |
| `stray_links.py mod_dir out_dir [--fix]` | Finds detached province pieces that create neighbours the province shouldn't have. With `--fix` it repaints noise, land-in-land pieces and stranded water: real lakes (per terrain.bmp) become the non-province lake colour, everything else becomes the host province. Islands are left alone. Run it twice, because a fix can expose another piece. |
