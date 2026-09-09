# Cross-lane register

Append-only. One entry per event. Do not edit or delete another lane's entry.

**Write here instead of editing a file you do not own.** The parallel arrangement (D8) is a
convention, not a tool guarantee — an edit outside your lane silently destroys another
agent's work with no warning and no conflict marker.

## When to add an entry

1. **You need a file another lane owns.** Say which file, which task, and why. Do not edit
   it. If the lane that owns it has finished, it may make the change for you; if not, Lane F
   makes it during integration.
2. **You are rejecting a recommendation in `DECISIONS.md`.** The D5 refinement is
   explicitly Lane A's to reject. Record the reasoning; a decision reversed without a
   written reason gets reversed back later.
3. **You found something that invalidates another lane's premise.** More urgent than the
   others — say so plainly and flag the affected lane by name.
4. **You finished.** One line, so dependent lanes know.

## Entries

### Template

```
### [YYYY-MM-DD] Lane X — <one-line summary>
**Type:** file request | decision rejection | invalidated premise | completion
**Affects:** Lane Y / <file path>
**Detail:** what and why, in a few sentences.
**Resolution:** filled in when settled.
```

---

### [2026-09-07] Lane 0 — register opened
**Type:** completion
**Affects:** all lanes
**Detail:** Release plan written and decisions recorded. Lanes A–E may start once Lane 0
reports the baseline commit.
**Resolution:** —
