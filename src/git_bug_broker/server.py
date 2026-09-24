"""stdio MCP server exposing a git-bug store as tools.

Configuration comes from the environment:
  GITBUG_BROKER_REPO   repository whose web UI git-bug-broker-start launched (required)
  GITBUG_BROKER_RULES  project rules file layered over rules/default.json (optional)

Every MCP client runs its own copy of this server. They share one web UI, and
the write lock in client.py serializes their writes.
"""
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import client as C
from . import rules as R

mcp = MCPServer(
    "git-bug",
    instructions=(
        "An issue store kept in git-bug. Use these tools instead of the git-bug "
        "CLI. Titles are present-tense claims about what the code does, with no leading number. "
        "Each entry carries exactly one area/<name> and one kind/<name> label; namespaces use a "
        "slash, never a colon. defect and chore bodies need 'What' and 'Done when' sections. "
        "A refused write returns every violation; fix them and retry. Free-text query terms "
        "return at most 10 hits, so filter with label:, status: or title: when completeness "
        "matters."),
)

_client = None


def cl():
    global _client
    if _client is None:
        _client = C.Client()
    return _client


def _run(name, *a, **kw):
    # Only a ToolError's text reaches the caller; the SDK reports any other
    # exception as a bare "Error executing tool". The client is built inside the
    # try so a missing endpoint or rules file is reported like any other failure.
    try:
        return getattr(cl(), name)(*a, **kw)
    except R.RuleViolation as e:
        raise ToolError(str(e)) from None
    except C.BrokerDown as e:
        raise ToolError(f"git-bug web UI unavailable: {e}") from None
    except (C.GraphQLError, KeyError, TimeoutError, FileNotFoundError) as e:
        raise ToolError(f"{type(e).__name__}: {e}") from None


@mcp.tool()
def file_entry(title: str, body: str, labels: list[str]) -> dict:
    """File a new entry. labels must include exactly one area/<name> and one kind/<name>
    (defect, chore, decision, investigation, idea); add filed-by/<agent> when an agent files it."""
    return _run("file_entry", title, body, labels)


@mcp.tool()
def comment(id: str, message: str) -> dict:
    """Add a comment to an entry, by id or unique id prefix."""
    return _run("comment", id, message)


@mcp.tool()
def edit_body(id: str, body: str) -> dict:
    """Replace an entry's body (its first comment). Checked against the entry's kind."""
    return _run("edit_body", id, body)


@mcp.tool()
def edit_comment(comment_id: str, message: str) -> dict:
    """Replace the text of one comment, by the comment id that get() returns."""
    return _run("edit_comment", comment_id, message)


@mcp.tool()
def relabel(id: str, add: list[str] | None = None, remove: list[str] | None = None) -> dict:
    """Add and remove labels in one operation. The resulting set must satisfy the standard,
    so swap an area with add=['area/new'], remove=['area/old'] in one call."""
    return _run("relabel", id, add or [], remove or [])


@mcp.tool()
def set_status(id: str, status: str, comment: str | None = None) -> dict:
    """Open or close an entry ('open' or 'closed'), optionally with a comment in the same
    operation. A closing comment should name the commit and the test that pins the fix."""
    return _run("set_status", id, status, comment)


@mcp.tool()
def set_title(id: str, title: str) -> dict:
    """Retitle an entry. The new title is checked against the standard."""
    return _run("set_title", id, title)


@mcp.tool()
def get(id: str) -> dict:
    """Read one entry: title, status, labels, body and comments with their ids."""
    return _run("get", id)


@mcp.tool()
def query(query: str = "status:open", first: int = 100) -> dict:
    """List entries matching a git-bug query, for example 'status:open label:area/api'
    or 'label:kind/defect sort:edit'. Returns ids, titles, status and labels, not bodies."""
    return _run("query", query, first)


def main():
    mcp.run("stdio")


if __name__ == "__main__":
    main()
