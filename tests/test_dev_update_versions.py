import pytest

from ligojcli.dev_update_versions import (
    TagShape,
    decide,
    major,
    matching,
    parse_stops,
    shape_of,
)

from .conftest import FIXTURES


def test_shape_of():
    assert shape_of("2.570-slim-jdk25") == TagShape(2, "-slim-jdk25")
    assert shape_of("26.6.0.123539-community") == TagShape(4, "-community")
    assert shape_of("19.1.1-ce.0") == TagShape(3, "-ce.0")
    assert shape_of("17") == TagShape(1, "")
    assert shape_of("latest") is None


def test_matching_excludes_other_flavours_and_prereleases(tags):
    jenkins = matching(tags("jenkins"), TagShape(2, "-slim-jdk25"))
    assert jenkins[-1] == (2, 587) and all(len(v) == 2 for v in jenkins)  # LTS x.y.z excluded
    assert matching(tags("postgres"), TagShape(1, ""))[-1] == (18,)  # 18beta3 / 18rc1 excluded
    assert matching(tags("gitlab"), TagShape(3, "-ce.0"))[-1] == (19, 5, 1)  # -rcN.ce.0 excluded
    assert matching(tags("nexus"), TagShape(3, ""))[-1] == (3, 97, 2)  # -alpine / -ubi excluded


def test_numeric_not_lexical(tags):
    assert matching(tags("sonarqube"), TagShape(4, "-community"))[-1] == (26, 10, 0, 133078)


STOPS = parse_stops((FIXTURES / "gitlab_upgrade_path.yml").read_text(encoding="utf-8"))


def test_parse_stops():
    assert (19, 2) in STOPS and (18, 11) in STOPS and STOPS == sorted(STOPS)


def test_unrestricted(tags):
    sonar = decide("sonarqube", "26.6.0.123539-community", None, tags("sonarqube"), False)
    assert sonar.targets == ("26.10.0.133078-community",)
    jenkins = decide("jenkins", "2.570-slim-jdk25", None, tags("jenkins"), False)
    assert jenkins.targets == ("2.587-slim-jdk25",)
    assert decide("keycloak", "26.6.1", None, tags("keycloak"), False).targets == ("26.8.1",)


def test_floating_tag_is_pinned(tags):
    assert decide("nexus", "latest", (3, 93, 2), tags("nexus"), False).targets == ("3.97.2",)
    assert decide("nexus", "latest", (3, 97, 2), tags("nexus"), False).targets == ("3.97.2",)


def test_postgres_same_major(tags):
    safe = decide("postgresql", "17", None, tags("postgres"), False)
    assert safe.targets == () and safe.newest == "18" and "--force for 18" in safe.held
    assert decide("postgresql", "17", None, tags("postgres"), True).targets == ("18",)


def test_artifactory_same_major(tags):
    # The OSS UI works on recent 7.x once JFrog Connect is disabled ('dev init' sets it)
    safe = decide("artifactory", "7.111.9", None, tags("artifactory"), False)
    assert safe.targets == ("7.161.26",) and safe.held is None
    with_8 = tags("artifactory") + ["8.0.1"]
    held = decide("artifactory", "7.111.9", None, with_8, False)
    assert held.targets == ("7.161.26",) and "--force for 8.0.1" in held.held
    assert decide("artifactory", "7.111.9", None, with_8, True).targets == ("8.0.1",)


def test_gitlab_stops(tags):
    safe = decide("gitlab", "latest", (19, 1, 1), tags("gitlab"), False, STOPS)
    assert safe.targets == ("19.2.9-ce.0",)
    forced = decide("gitlab", "latest", (19, 1, 1), tags("gitlab"), True, STOPS)
    assert forced.targets == ("19.2.9-ce.0", "19.5.1-ce.0")


def test_charts_same_major(tags):
    assert decide("harbor", "1.18.0", None, tags("harbor_chart"), False).targets == ("1.19.1",)
    argocd = decide("argocd", "9.0.0", None, tags("argocd_chart"), False)
    assert argocd.targets == ("9.7.1",) and argocd.newest == "10.1.2"


def test_legacy(tags):
    assert decide("openldap", "latest", (2, 6, 10), tags("openldap"), True).targets == ()


# Review Focus 1-4
def test_unrecognized_tag(tags):
    d = decide("sonarqube", "developer", None, tags("sonarqube"), True)
    assert d.targets == () and "unrecognized tag" in d.held


def test_unknown_floating_version_never_jumps(tags):
    assert decide("gitlab", "latest", None, tags("gitlab"), True, STOPS).targets == ()


def test_never_downgrade(tags):
    assert decide("keycloak", "27.0.0", None, tags("keycloak"), True).targets == ()


def test_no_upstream_tags():
    d = decide("keycloak", "26.6.1", None, [], False)
    assert d.targets == () and d.held == "no matching upstream release"


def test_gitlab_without_upgrade_path_never_jumps(tags):
    d = decide("gitlab", "latest", (19, 1, 1), tags("gitlab"), True, None)
    assert d.targets == () and "upgrade path" in d.held


# Final review fixes
def test_unbounded_ranged_decisions_do_not_refresh(tags):
    # C1: re-pulling a floating tag would jump past the safe range (GitLab stops, PG major)
    assert decide("gitlab", "latest", None, tags("gitlab"), False, STOPS).refresh is False
    assert decide("gitlab", "latest", (19, 1, 1), tags("gitlab"), False, None).refresh is False
    assert decide("postgresql", "latest", None, tags("postgres"), False).refresh is False
    assert decide("artifactory", "latest", None, tags("artifactory"), False).refresh is False
    assert decide("postgresql", "17", None, tags("postgres"), False).refresh is True
    assert decide("nexus", "latest", None, tags("nexus"), False).refresh is True


def test_major():
    # I3: a minor PostgreSQL tag moving within its major is not a major change
    assert major("17.2") == 17 and major("17.6") == 17 and major("18") == 18
    assert major("latest") is None


def test_parse_stops_rejects_malformed():
    # I10: an HTML page served with 200, or a broken entry, must not crash the command
    with pytest.raises(ValueError):
        parse_stops("<html><body>Sign in</body></html>")
    with pytest.raises(ValueError):
        parse_stops("- major: 19\n")


def test_gitlab_missing_stop_blocks(tags):
    # M5: a required stop with no published tag (truncated list) must not be crossed
    without_19_2 = [tag for tag in tags("gitlab") if not tag.startswith("19.2.")]
    d = decide("gitlab", "latest", (19, 1, 1), without_19_2, True, STOPS)
    assert d.targets == () and "19.2" in d.held


def test_gitlab_on_a_stop(tags):
    # already on the 19.2 stop: a newer 19.2 patch first, then onward; at its latest patch, onward
    assert decide("gitlab", "19.2.0-ce.0", None, tags("gitlab"), False, STOPS).targets == (
        "19.2.9-ce.0",
    )
    assert decide("gitlab", "19.2.9-ce.0", None, tags("gitlab"), False, STOPS).targets == (
        "19.5.1-ce.0",
    )
