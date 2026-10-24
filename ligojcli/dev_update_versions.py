#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Version selection for `dev update`, without any I/O: the shape of an image tag (or Helm chart
# version), the upstream releases sharing that shape, and the target each service may move to.
#
# A tag shape is its count of numeric components plus its literal suffix, so a flavour never
# changes: '2.570-slim-jdk25' only matches 'x.y-slim-jdk25' (never the LTS 'x.y.z-slim-jdk25'),
# '26.6.0.123539-community' only 'a.b.c.d-community', and pre-releases ('18beta3',
# '10.0.0-rc2.ce.0', ...) never match a release shape.
#
import re
from dataclasses import dataclass

import yaml

_LEADING_VERSION = re.compile(r"^(\d+(?:\.\d+)*)(.*)$")

# Repositories that no longer publish anything: only a re-pull makes sense.
LEGACY = {"openldap"}
# Safe range per service, crossed only with --force (see the 'dev update' design).
SAFE_RANGES = {
    "postgresql": "major",
    "gitlab": "stops",
    "artifactory": "major",
    "harbor": "major",
    "argocd": "major",
}
_HELD = {
    "major": "same major only, --force for {newest}",
    "stops": "next required upgrade stop only, --force for {newest}",
}


def parse_version(text):
    """'26.6.0.123539' -> (26, 6, 0, 123539); None unless dot-separated integers only."""
    if not re.fullmatch(r"\d+(?:\.\d+)*", text or ""):
        return None
    return tuple(int(part) for part in text.split("."))


@dataclass(frozen=True)
class TagShape:
    components: int
    suffix: str

    def match(self, tag):
        """Version of a tag having exactly this shape, else None."""
        found = _LEADING_VERSION.match(tag)
        if not found or found.group(2) != self.suffix:
            return None
        version = parse_version(found.group(1))
        return version if len(version) == self.components else None

    def format(self, version):
        return ".".join(str(part) for part in version) + self.suffix


# Shape of the explicit tags behind a floating one ('latest'), used to pin it.
FLOATING_SHAPES = {"gitlab": TagShape(3, "-ce.0"), "nexus": TagShape(3, "")}


@dataclass(frozen=True)
class Decision:
    targets: tuple = ()  # tags (or chart versions) to deploy in order; () = keep and refresh the current one
    newest: str | None = None  # newest upstream release of the flavour, whatever the safe range
    held: str | None = None  # why 'newest' is not reached
    # False when re-pulling the current tag could cross the safe range unchecked (unknown version
    # or tag, no GitLab upgrade path): a floating ':latest' would jump straight to the newest.
    refresh: bool = True


def shape_of(tag):
    """Shape of a versioned tag; None for a floating one such as 'latest'."""
    found = _LEADING_VERSION.match(tag)
    if not found:
        return None
    return TagShape(len(found.group(1).split(".")), found.group(2))


def matching(tags, shape):
    """Versions of the tags sharing the shape, sorted ascending, without duplicates."""
    return sorted({version for version in map(shape.match, tags) if version is not None})


def major(tag):
    """First version component of a versioned tag ('17.2' -> 17), None for a floating one."""
    shape = shape_of(tag)
    version = shape.match(tag) if shape else None
    return version[0] if version else None


def parse_stops(yaml_text):
    """GitLab required upgrade stops, from its 'config/upgrade_path.yml', as sorted (major, minor)."""
    try:
        entries = yaml.safe_load(yaml_text)
        if not isinstance(entries, list):
            raise TypeError(type(entries).__name__)
        return sorted({(int(e["major"]), int(e["minor"])) for e in entries})
    except (yaml.YAMLError, TypeError, KeyError, ValueError) as error:
        raise ValueError(f"[dev] Unreadable GitLab upgrade path ({error})") from error


def gitlab_hops(current, candidates, stops):
    """(hops, missing): latest patch of every required stop up to the newest candidate, then the
    newest. A stop in between with no published patch ends the hops there: it cannot be crossed.
    """
    if not candidates:
        return [], None
    newest = candidates[-1]
    hops = []
    for stop in stops:
        if stop >= newest[:2]:
            break
        if stop < current[:2]:
            continue  # already past this stop
        patches = [version for version in candidates if version[:2] == stop]
        if not patches:
            if stop > current[:2]:
                return hops, stop
            continue  # on this stop, at its latest patch
        hops.append(patches[-1])
    if newest > (hops[-1] if hops else current):
        hops.append(newest)
    return hops, None


def decide(service, current_tag, current_version, tags, force, stops=None):
    """Target of a service running 'current_tag' (version 'current_version' when the tag floats)."""
    if service in LEGACY:
        return Decision(held="legacy repository, no newer upstream")
    # Without a known position, a ranged service must not even be re-pulled.
    refresh = service not in SAFE_RANGES
    shape = shape_of(current_tag)
    floating = shape is None
    if floating:
        shape = FLOATING_SHAPES.get(service)
        if shape is None:
            return Decision(held=f"unrecognized tag '{current_tag}'", refresh=refresh)
    current = current_version or shape.match(current_tag)
    if current is None:
        return Decision(held="current version unknown", refresh=refresh)
    versions = matching(tags, shape)
    if not versions:
        return Decision(held="no matching upstream release", refresh=refresh)
    newest = shape.format(versions[-1])
    candidates = [version for version in versions if version > current]
    same_major = [version for version in candidates if version[0] == current[0]]
    safe_range = SAFE_RANGES.get(service)
    if safe_range == "stops":
        if not stops:
            return Decision(
                newest=newest,
                held="GitLab upgrade path unavailable, cannot plan stops",
                refresh=not floating,
            )
        hops, missing = gitlab_hops(current, candidates, stops)
        if missing and not hops:
            stop = ".".join(map(str, missing))
            return Decision(
                newest=newest,
                held=f"required upgrade stop {stop} not found upstream, cannot cross it",
                refresh=not floating,
            )
        allowed = hops if force else hops[:1]
    elif safe_range == "major":
        allowed = candidates if force else same_major
    else:
        allowed = candidates
    if safe_range != "stops":
        allowed = allowed[-1:]
    targets = tuple(shape.format(version) for version in allowed)
    if not targets and floating and current in versions:
        targets = (shape.format(current),)  # pin the floating tag to its explicit equivalent
    reached = allowed[-1] if allowed else current
    held = None
    if versions[-1] > reached and safe_range in _HELD:
        held = _HELD[safe_range].format(newest=newest)
    return Decision(targets=targets, newest=newest, held=held)
