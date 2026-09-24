"""Issue conventions, checked before any write reaches git-bug.

The rules are data (rules/*.json). A project supplies its own file through
GITBUG_BROKER_RULES; it is layered over rules/default.json key by key, so a
project file only has to name what differs (usually `areas` and `flags`).
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))


class RuleViolation(ValueError):
    """Raised with every violation found, one per line, so a caller fixes all at once."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("write refused by the conventions check:\n- " + "\n- ".join(self.problems))


def load_rules(path=None):
    with open(os.path.join(HERE, "rules", "default.json"), encoding="utf-8") as f:
        rules = json.load(f)
    path = path or os.environ.get("GITBUG_BROKER_RULES")
    if path:
        with open(path, encoding="utf-8") as f:
            override = json.load(f)
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(rules.get(k), dict):
                rules[k] = {**rules[k], **v}
            else:
                rules[k] = v
    return rules


def check_title(rules, title, kind=None):
    t = rules["title"]
    out = []
    s = (title or "").strip()
    if not s:
        return ["title is empty"]
    if "\n" in s:
        out.append("title must be one line")
    if len(s) > t["max_chars"]:
        out.append(f"title is {len(s)} characters, limit {t['max_chars']}")
    if re.match(t["leading_number_pattern"], s, re.I):
        out.append("title starts with a number; refer to entries by their git-bug id")
    words = re.findall(r"[\w'`]+", s.lower())
    stripped = [w.strip("`") for w in words]
    if len(words) < t["min_words"] and not set(stripped) & set(t["claim_markers"]):
        out.append(f"title '{s}' reads as a topic; write a present-tense claim about what the "
                   "code does (for example 'retry() returns nil when every attempt fails')")
    if kind in t["fix_prefix_rejected_for"] and stripped and stripped[0] in t["fix_prefixes"]:
        out.append(f"a {kind} title states what is wrong, not the fix; '{words[0]} ...' "
                   "names the fix")
    return out


def check_labels(rules, labels):
    """Validate a complete label set (what the entry will carry after the write)."""
    out = []
    pat = re.compile(rules["label_pattern"])
    areas, kinds = rules["areas"], rules["kinds"]
    counts = {p: 0 for p in rules["exactly_one"]}
    for lab in labels:
        if ":" in lab:
            out.append(f"label '{lab}' uses a colon; use a slash ('{lab.replace(':', '/')}'), "
                       "because git-bug's query language reads a colon as a second qualifier")
            continue
        if not pat.match(lab):
            out.append(f"label '{lab}' does not match {rules['label_pattern']}")
            continue
        for p in counts:
            if lab.startswith(p):
                counts[p] += 1
        if lab.startswith("area/"):
            name = lab[5:]
            if not rules.get("areas_open") and name not in areas:
                out.append(f"unknown area '{name}'; known: {', '.join(areas)}")
        elif lab.startswith("kind/"):
            if lab[5:] not in kinds:
                out.append(f"unknown kind '{lab[5:]}'; known: {', '.join(kinds)}")
        elif lab in rules["flags"]:
            pass
        elif any(lab.startswith(p) and len(lab) > len(p) for p in rules["free_prefixes"]):
            pass
        else:
            out.append(f"label '{lab}' is not a known flag ({', '.join(rules['flags'])}) or "
                       f"namespace ({', '.join(rules['exactly_one'] + rules['free_prefixes'])})")
    for p, n in counts.items():
        if n != 1:
            out.append(f"entry must carry exactly one {p} label, has {n}")
    return out


def kind_of(labels):
    for lab in labels:
        if lab.startswith("kind/"):
            return lab[5:]
    return None


def check_body(rules, body, kind):
    out = []
    if not (body or "").strip():
        return ["body is empty"]
    for name in rules["body_sections"].get(kind or "", []):
        rx = rules["section_pattern"].replace("{name}", re.escape(name))
        if not re.search(rx, body):
            out.append(f"a {kind} body needs a '{name}' section (for example '**{name}.** ...')")
    return out


def check_entry(rules, title, body, labels):
    kind = kind_of(labels)
    problems = check_labels(rules, labels) + check_title(rules, title, kind) + check_body(rules, body, kind)
    if problems:
        raise RuleViolation(problems)
