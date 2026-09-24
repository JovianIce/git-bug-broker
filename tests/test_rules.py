from git_bug_broker import rules as R

BODY = "**What** parseConfig drops the field.\n**Done when** the timeout is honoured."


def problems(title, labels, body=BODY, rules=None):
    try:
        R.check_entry(rules or R.load_rules(), title, body, labels)
        return ""
    except R.RuleViolation as e:
        return str(e)


def test_claim_title_passes():
    assert problems("The retry loop never backs off after a 429", ["area/api", "kind/defect"]) == ""


def test_topic_title_rejected():
    assert "topic" in problems("Retry handling", ["area/api", "kind/defect"])


def test_fix_title_rejected_for_defect():
    assert "fix" in problems("Add backoff to the retry loop", ["area/api", "kind/defect"])


def test_leading_number_rejected():
    assert problems("12. The retry loop never backs off", ["area/api", "kind/defect"]) != ""


def test_colon_label_rejected():
    assert "colon" in problems("The retry loop never backs off after a 429", ["area:api", "kind/defect"])


def test_exactly_one_area_and_kind():
    assert problems("The retry loop never backs off after a 429", ["area/api", "area/ui", "kind/defect"]) != ""
    assert problems("The retry loop never backs off after a 429", ["area/api"]) != ""


def test_defect_body_needs_sections():
    assert "Done when" in problems("The retry loop never backs off after a 429", ["area/api", "kind/defect"], body="It is broken.")


def test_project_file_closes_areas(tmp_path):
    f = tmp_path / "rules.json"
    f.write_text('{"areas": ["api"], "areas_open": false}', encoding="utf-8")
    rules = R.load_rules(str(f))
    assert problems("The retry loop never backs off after a 429", ["area/api", "kind/defect"], rules=rules) == ""
    assert "unknown area" in problems("The retry loop never backs off after a 429", ["area/ui", "kind/defect"], rules=rules)


CLAIM = "The retry loop never backs off after a 429"


def test_long_title_rejected():
    assert "limit 80" in problems("The retry loop " + "never " * 20 + "backs off", ["area/api", "kind/defect"])


def test_multiline_title_rejected():
    assert "one line" in problems("The retry loop never backs off\nafter a 429", ["area/api", "kind/defect"])


def test_unknown_kind_rejected():
    assert "unknown kind" in problems(CLAIM, ["area/api", "kind/bug"])


def test_unknown_flag_or_namespace_rejected():
    assert "not a known flag" in problems(CLAIM, ["area/api", "kind/defect", "urgent"])
    assert "not a known flag" in problems(CLAIM, ["area/api", "kind/defect", "team/web"])
    assert "not a known flag" in problems(CLAIM, ["area/api", "kind/defect", "source/"])


def test_uppercase_label_rejected():
    assert "does not match" in problems(CLAIM, ["area/API", "kind/defect"])


def test_chore_body_needs_sections():
    out = problems("Rename the config loader to settings", ["area/api", "kind/chore"], body="Tidy up.")
    assert "What" in out and "Done when" in out


def test_fix_verb_accepted_for_chore():
    assert problems("Rename the config loader to settings", ["area/api", "kind/chore"]) == ""
