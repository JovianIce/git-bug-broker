# git-bug-broker

An MCP server that lets several agents file, label and close issues in one [git-bug](https://github.com/git-bug/git-bug) store (a distributed issue tracker that keeps issues in git refs) while its web UI stays open.

![An issue filed, reproduced, fixed and closed by an agent and its subagents, seen in git-bug's web UI](https://raw.githubusercontent.com/JovianIce/git-bug-broker/main/docs/agent-bug-sample.png)

git-bug keeps issues inside the repository as git objects, so agents can track work
next to the code with no hosted tracker, API token or network. Through this server an
agent can open an issue for a bug it finds, comment on it as it investigates, label it,
read what other agents have written, and close it with a note naming the commit that
fixed it. Issues are versioned like commits and sync through any git remote with
`git bug push` and `git bug pull`, so the record carries over between sessions and
between agents.

`git-bug webui` holds the search index for as long as it runs, and every CLI command waits on it without saying so. The broker talks to the web UI's GraphQL endpoint instead, takes a file lock for each write, and refuses any write that breaks the project's conventions: claim-style titles, one `area/` and one `kind/` label, required body sections. A rejected write lists every problem at once. Unlike a wrapper around the CLI, it keeps working while `git-bug webui` is open, and concurrent writes don't collide. The client is also a small Python library, so a script can write to the store while the UI is open too.

Works with git-bug 0.11. Tested on Windows; the Linux and macOS paths are written but
untested.

## Install

```sh
pip install git-bug-broker
```

or from a checkout of [the repository](https://github.com/JovianIce/git-bug-broker), `pip install -e .`. Needs Python 3.10+ and `git-bug` on `PATH`.

## Run

```sh
git-bug-broker-start <repo>            # start the web UI (reuses one already running)
git-bug-broker-start <repo> --status
git-bug-broker-start <repo> --stop
```

It prints the web UI's URL. An issue is at `<url>/_/issues/<id>`, where `<id>` is the
short id the tools return. The issue list starts filtered to `status:open`; clear the
search box to see closed issues too. `--stop` only stops the process it started.

## Use from Python

```python
from git_bug_broker.client import Client

c = Client(repo="/path/to/repo")
c.file_entry(
    "The retry loop never backs off after a 429",
    "**What** retry() sleeps a fixed 1 s.
**Done when** the delay doubles per attempt.",
    ["area/api", "kind/defect"],
)
```

## Connect an MCP client

`.mcp.json` for Claude Code:

```json
{
  "mcpServers": {
    "git-bug": {
      "command": "git-bug-broker",
      "env": {
        "GITBUG_BROKER_REPO": "/path/to/repo",
        "GITBUG_BROKER_RULES": "/path/to/repo/.git-bug-rules.json"
      }
    }
  }
}
```

Any stdio MCP client takes the same command and env.

`GITBUG_BROKER_RULES` is optional. Without it the defaults in
`src/git_bug_broker/rules/default.json` apply and any area name is accepted.
`examples/rules.example.json` shows a project file with a fixed area list.

`GITBUG_BROKER_URL` points the client at a web UI the broker did not start, for example one on another port.

Tools: `file_entry`, `comment`, `edit_body`, `edit_comment`, `relabel`, `set_status`,
`set_title`, `get`, `query`. A rejected write lists every problem at once.

## Rules

What gets checked is in [CONVENTIONS.md](https://github.com/JovianIce/git-bug-broker/blob/main/CONVENTIONS.md). Briefly:

- a title is a claim about the code, at most 80 characters, with no leading number
- exactly one `area/` and one `kind/` label, with a slash, never a colon
- defects and chores have `What` and `Done when` sections

## Why the lock

git-bug 0.11 applies an operation and commits it in two unguarded steps. When two
writes hit the same issue at once both land, but one caller is told
`can't commit an entity with no pending operation`, and a retry duplicates the write.
The broker holds `<repo>/.git/git-bug-broker/write.lock` for each write. Reads don't
lock.

Measured on git-bug 0.11 on Windows: with the lock, 24 parallel writes from 4 server processes, 12 of them to one shared
issue, finished in 3.7 s with no errors. Without it, 28 of 30 concurrent writes to one
issue reported failure although all 30 had landed.

## Limitations

- The web UI has to be running. If it isn't, every tool says so and nothing is queued.
- Filing an issue is two mutations, create then label. A crash in between leaves an
  unlabelled issue; the error gives its id.
- The web UI binds to 127.0.0.1 with no authentication.
- Edits made in the web UI aren't checked against the rules.
- Free-text search returns at most 10 results. `title:`, `label:` and `status:`
  filters return everything.

## Development

```sh
pip install -e .[dev]
pytest
```

`tools/view.py` renders the store as a static HTML page and a JSON Lines snapshot. It reads through the CLI, so run it while the web UI is stopped; anything reading its output needs neither.

## License

MIT
