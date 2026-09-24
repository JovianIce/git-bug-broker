# Conventions

These are the conventions the default rules enforce, plus the ones that can't be
checked mechanically. They're what I use; change the rules file to suit your project.

## What goes in the store

An issue is either a claim about the code that someone can check by reading it
("`parseConfig` ignores the timeout field"), or an open question that a measurement
will close ("whether the cache helps under concurrent load is unmeasured").

Results from runs, benchmarks or user reports go in a document with enough detail to
reproduce them, and the issue links to it. One defect per issue.

## Titles

- A present-tense claim. "The retry loop never backs off after a 429", not "Retry
  handling" and not "Add backoff to the retry loop".
- One line, at most 80 characters.
- No numbering. Refer to issues by their git-bug id.

The broker checks length, leading numbers, and fix verbs on defects and
investigations. It also rejects a title under four words that contains none of the claim markers
(`is`, `never`, `returns`, `ignores`...) as a topic; tune `min_words` and `claim_markers`.

## Labels

Each issue has exactly one `area/` label and exactly one `kind/` label.

| label | values |
|---|---|
| `area/<name>` | a part of the codebase: `api`, `storage`, `ui`... |
| `kind/<name>` | `defect`, `chore`, `decision`, `investigation`, `idea` |
| `source/<name>` | the review or pass that filed it, e.g. `source/audit-2026-09` |
| `filed-by/<name>` | the agent that filed it |
| flags | `blocks` - stops other work; `needs-provenance` - rests on data that does not say how to reproduce it; and any your project adds |

Use a slash, never a colon. git-bug's query language reads `label:area:api` as two
qualifiers and errors, while `label:area/api` works. The broker rejects colons and any
label that isn't a known flag or under one of these prefixes.

Labels are lowercase: letters, digits, `.`, `/` and `-`. A `source/` or `filed-by/` label
needs a name after the slash.

Sort defects by area rather than priority, so "what's broken where I'm about to work"
is a single query.

## Body

Defects and chores need two sections:

- **What**: the function, file and line at a named commit, with the line quoted, since
  line numbers go stale.
- **Done when**: one condition that can be observed.

**Why it matters** and **Direction** are optional.

## Working with issues

- Open an issue when work starts and close it when the change lands.
- Close issues; don't delete them.
- Keep closing comments short: what changed, the commit, and the test that covers it.
- Add a comment rather than rewriting the body, so the history stays readable.

## Agents

- An agent labels what it files `filed-by/<agent>` instead of changing git-bug's
  identity, which lives in git config and is shared. Labels can be edited, so this
  isn't tamper-proof.
- Everything is written under one git-bug identity, the one the web UI runs as. A
  comment that reports a subagent's run starts with `**Subagent run: <role>**` on its
  own line, so the hand-offs are readable in the web UI.
- For bulk changes, have one agent write and show a person the list first.
- Agents that only read can use the snapshot from `tools/view.py`, made while
  the web UI is stopped.

## git-bug notes

- While `git-bug webui` runs, CLI commands hang until it stops.
- git-bug records real wall-clock time and timezone inside each operation and ignores
  `GIT_AUTHOR_DATE`, `GIT_COMMITTER_DATE` and `TZ`. The timestamp is part of the
  content hash, so it can't be rewritten later. Don't push `refs/bugs/*` unless you're
  fine publishing that. The default push refspec leaves them out.
- `git-bug bug new -t "title" -F file` ignores `-t` and uses the file's first line as
  the title. Use `-m`.
- If searches look wrong after editing refs directly or after a killed write, delete
  `.git/git-bug`; it's a cache and gets rebuilt.
- Free-text search stops at 10 results. Use `title:` and `label:` to check for
  duplicates.
- Put a timeout on git-bug calls from scripts. A timeout usually means something holds
  the index lock.
