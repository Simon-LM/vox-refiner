# VoxRefiner — Update Troubleshooting

---

## Update blocked — "Local tracked changes detected"

**Cause:** a file tracked by git was modified, renamed, or deleted locally.

**Fix:**
```bash
cd ~/.local/bin/vox-refiner
git status              # identify the affected file(s)
git restore <file>      # restore each file listed under "deleted" or "modified"
```
Then retry **[a] Apply update** from the menu.

**Common triggers:**
- Renaming `launch-vox-refiner.example.sh` to `.old` or another name
- Manually editing a script tracked by git

> Your personal files (`.env`, `launch-vox-refiner.sh`, `context.txt`, `history.txt`) are in `.gitignore` and will never cause this error.

---

## Update applied but nothing changed

**Cause:** you were already on the latest version, or the fast-forward failed silently.

**Fix:**
```bash
cd ~/.local/bin/vox-refiner
git log --oneline -5    # check recent commits
git pull                # force a pull if needed
```

---

## "Not a git repository" error

**Cause:** VoxRefiner was installed by copying files manually instead of via `git clone`.

**Fix:** reinstall using git:
```bash
git clone https://github.com/Simon-LM/vox-refiner.git ~/.local/bin/vox-refiner
```

---

## More help

Report issues at: https://github.com/Simon-LM/vox-refiner/issues
