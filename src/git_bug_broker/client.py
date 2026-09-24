"""Client over the git-bug web UI's GraphQL endpoint.

One `git-bug webui` process owns the store and its BoltDB index lock, and every
read and write goes to it over HTTP, so nothing here runs the git-bug CLI.

Writes also take a file lock (`<repo>/.git/git-bug-broker/write.lock`) for the
length of one logical write. git-bug v0.11's resolvers apply an operation and
commit it in two steps without holding the entity in between, so when two writes
hit the same entry both land but one caller gets "can't commit an entity with no
pending operation". That false failure invites a retry that duplicates the write.

Standard library only; the MCP server is the only part with a dependency.
"""
import contextlib
import json
import os
import time
import urllib.error
import urllib.request

from . import rules as R

STATE_DIRNAME = "git-bug-broker"
LOCK_TIMEOUT_S = 30.0
HTTP_TIMEOUT_S = 30.0


class BrokerDown(RuntimeError):
    pass


class GraphQLError(RuntimeError):
    pass


def state_dir(repo):
    return os.path.join(os.path.abspath(repo), ".git", STATE_DIRNAME)


def read_endpoint(repo):
    path = os.path.join(state_dir(repo), "endpoint.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


@contextlib.contextmanager
def _file_lock(path, timeout=LOCK_TIMEOUT_S):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a+b")
    deadline = time.monotonic() + timeout
    try:
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"write lock {path} held for more than {timeout}s")
                    time.sleep(0.005)
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            while True:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"write lock {path} held for more than {timeout}s")
                    time.sleep(0.005)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    finally:
        f.close()


BUG_FIELDS = """id humanId status title createdAt lastEdit
  labels { name }
  author { displayName }
  comments(first: 500) { nodes { id message author { displayName } } }"""

LIST_FIELDS = "id humanId status title lastEdit labels { name }"


class Client:
    def __init__(self, repo=None, url=None, rules_path=None):
        self.repo = repo or os.environ.get("GITBUG_BROKER_REPO")
        url = url or os.environ.get("GITBUG_BROKER_URL")
        if not url and self.repo:
            ep = read_endpoint(self.repo)
            url = ep and ep.get("url")
        if not url:
            raise BrokerDown("no broker endpoint: set GITBUG_BROKER_REPO to a repository whose "
                             "web UI was started with git-bug-broker-start, or GITBUG_BROKER_URL")
        self.url = url.rstrip("/") + "/graphql" if not url.endswith("/graphql") else url
        self.rules = R.load_rules(rules_path)
        lock_home = state_dir(self.repo) if self.repo else os.path.join(
            os.environ.get("TEMP", "/tmp"), STATE_DIRNAME)
        self.lock_path = os.path.join(lock_home, "write.lock")

    # transport -----------------------------------------------------------

    def _gql(self, query, variables=None):
        data = json.dumps({"query": query, "variables": variables or {}}).encode()
        req = urllib.request.Request(self.url, data, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
                out = json.load(r)
        except urllib.error.URLError as e:
            raise BrokerDown(f"git-bug web UI at {self.url} is not answering ({e.reason}); "
                             "start it with git-bug-broker-start.") from e
        if out.get("errors"):
            raise GraphQLError("; ".join(e.get("message", str(e)) for e in out["errors"]))
        return out["data"]

    def _write(self, query, variables, verify=None, bug_id=None):
        """Run one mutation under the write lock.

        If git-bug still reports "no pending operation" (possible when another
        writer, such as the web UI itself, skips the lock), `verify(bug)` checks
        whether the change landed anyway."""
        with _file_lock(self.lock_path):
            try:
                return self._gql(query, variables)
            except GraphQLError as e:
                if "no pending operation" in str(e) and verify is not None:
                    bug = self.get(bug_id or variables["i"]["prefix"], _raw=True)
                    if verify(bug):
                        return {"verified_after_race": True}
                raise

    # reads ---------------------------------------------------------------

    def get(self, id_prefix, _raw=False):
        d = self._gql("query($p:String!){repository{bug(prefix:$p){%s}}}" % BUG_FIELDS,
                      {"p": id_prefix})
        bug = d["repository"]["bug"]
        if bug is None:
            raise KeyError(f"no entry with id prefix '{id_prefix}'")
        return bug if _raw else _flatten(bug)

    def query(self, query="status:open", first=100):
        """List entries matching a git-bug query (status:, label:, title:, author:, sort:).

        Free-text terms go through bleve, which returns at most 10 hits."""
        d = self._gql("query($q:String,$n:Int){repository{allBugs(query:$q,first:$n)"
                      "{totalCount nodes{%s}}}}" % LIST_FIELDS, {"q": query, "n": first})
        conn = d["repository"]["allBugs"]
        return {"total": conn["totalCount"],
                "entries": [{"id": n["humanId"], "full_id": n["id"], "status": n["status"].lower(),
                             "title": n["title"], "labels": sorted(l["name"] for l in n["labels"]),
                             "last_edit": n["lastEdit"]} for n in conn["nodes"]]}

    # writes --------------------------------------------------------------

    def file_entry(self, title, body, labels):
        labels = sorted(set(labels))
        R.check_entry(self.rules, title, body, labels)
        with _file_lock(self.lock_path):
            d = self._gql("mutation($i:BugCreateInput!){bugCreate(input:$i){bug{id humanId}}}",
                          {"i": {"title": title.strip(), "message": body}})
            bid = d["bugCreate"]["bug"]["id"]
            try:
                self._gql("mutation($i:BugChangeLabelInput){bugChangeLabels(input:$i){results{status}}}",
                          {"i": {"prefix": bid, "added": labels}})
            except Exception as e:
                raise GraphQLError(f"entry {bid[:7]} created but labelling failed: {e}") from e
        return {"id": bid[:7], "full_id": bid}

    def comment(self, id_prefix, message):
        if not message.strip():
            raise R.RuleViolation(["comment is empty"])
        bug = self.get(id_prefix, _raw=True)
        self._write("mutation($i:BugAddCommentInput!){bugAddComment(input:$i){bug{id}}}",
                    {"i": {"prefix": bug["id"], "message": message}},
                    verify=lambda b: any(c["message"] == message for c in b["comments"]["nodes"]))
        return {"id": bug["humanId"], "comments": len(bug["comments"]["nodes"]) + 1}

    def edit_body(self, id_prefix, body):
        bug = self.get(id_prefix, _raw=True)
        kind = R.kind_of([l["name"] for l in bug["labels"]])
        problems = R.check_body(self.rules, body, kind)
        if problems:
            raise R.RuleViolation(problems)
        target = bug["comments"]["nodes"][0]["id"]
        self._write("mutation($i:BugEditCommentInput!){bugEditComment(input:$i){bug{id}}}",
                    {"i": {"targetPrefix": target, "message": body}},
                    verify=lambda b: b["comments"]["nodes"][0]["message"] == body, bug_id=bug["id"])
        return {"id": bug["humanId"], "edited": "body"}

    def edit_comment(self, comment_id, message):
        self._write("mutation($i:BugEditCommentInput!){bugEditComment(input:$i){bug{id}}}",
                    {"i": {"targetPrefix": comment_id, "message": message}})
        return {"comment": comment_id[:12], "edited": True}

    def relabel(self, id_prefix, add=(), remove=()):
        add, remove = sorted(set(add)), sorted(set(remove))
        with _file_lock(self.lock_path):
            bug = self.get(id_prefix, _raw=True)
            current = {l["name"] for l in bug["labels"]}
            result = (current | set(add)) - set(remove)
            problems = R.check_labels(self.rules, sorted(result))
            if problems:
                raise R.RuleViolation(problems)
            inp = {"prefix": bug["id"]}
            if add:
                inp["added"] = add
            if remove:
                inp["Removed"] = remove  # capital R is the v0.11 schema's spelling
            self._gql("mutation($i:BugChangeLabelInput){bugChangeLabels(input:$i)"
                      "{results{label{name} status}}}", {"i": inp})
        return {"id": bug["humanId"], "labels": sorted(result)}

    def set_status(self, id_prefix, status, comment=None):
        status = status.lower()
        if status not in ("open", "closed"):
            raise R.RuleViolation([f"status must be 'open' or 'closed', not '{status}'"])
        bug = self.get(id_prefix, _raw=True)
        want = status.upper()
        verify = lambda b: b["status"] == want  # noqa: E731
        if comment:
            m = "bugAddCommentAndClose" if status == "closed" else "bugAddCommentAndReopen"
            t = "BugAddCommentAndCloseInput" if status == "closed" else "BugAddCommentAndReopenInput"
            self._write("mutation($i:%s!){%s(input:$i){bug{status}}}" % (t, m),
                        {"i": {"prefix": bug["id"], "message": comment}}, verify=verify)
        elif bug["status"] != want:
            m = "bugStatusClose" if status == "closed" else "bugStatusOpen"
            t = "BugStatusCloseInput" if status == "closed" else "BugStatusOpenInput"
            self._write("mutation($i:%s!){%s(input:$i){bug{status}}}" % (t, m),
                        {"i": {"prefix": bug["id"]}}, verify=verify)
        return {"id": bug["humanId"], "status": status}

    def set_title(self, id_prefix, title):
        bug = self.get(id_prefix, _raw=True)
        problems = R.check_title(self.rules, title, R.kind_of([l["name"] for l in bug["labels"]]))
        if problems:
            raise R.RuleViolation(problems)
        self._write("mutation($i:BugSetTitleInput!){bugSetTitle(input:$i){bug{title}}}",
                    {"i": {"prefix": bug["id"], "title": title.strip()}},
                    verify=lambda b: b["title"] == title.strip())
        return {"id": bug["humanId"], "title": title.strip()}


def _flatten(bug):
    cs = bug["comments"]["nodes"]
    return {"id": bug["humanId"], "full_id": bug["id"], "status": bug["status"].lower(),
            "title": bug["title"], "labels": sorted(l["name"] for l in bug["labels"]),
            "author": bug["author"]["displayName"], "created": bug["createdAt"],
            "last_edit": bug["lastEdit"], "body": cs[0]["message"] if cs else "",
            "comments": [{"id": c["id"], "author": c["author"]["displayName"],
                          "message": c["message"]} for c in cs[1:]]}
