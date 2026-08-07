"""Promote CHANGELOG.md's [Unreleased] section to a released version.

Used by .github/workflows/release.yml. Rewrites CHANGELOG.md in place
(new empty Unreleased section on top, the old Unreleased content becomes
the new version's section, compare links updated) and writes the old
Unreleased body to a notes file for use as the GitHub Release description.
"""

import datetime
import re
import sys

REPO_URL = "https://github.com/nerdmonkey/microweaver-framework"
CHANGELOG_PATH = "CHANGELOG.md"

SECTION_RE = re.compile(
    r"^## \[Unreleased\]\n(?P<body>.*?)(?=\n## \[)", re.DOTALL | re.MULTILINE
)
LINK_RE = re.compile(r"^\[Unreleased\]: .*\n(?P<rest>(?:\[.*\n?)*)", re.MULTILINE)
FIRST_VERSION_LINK_RE = re.compile(r"^\[(?P<version>\d+\.\d+\.\d+)\]:", re.MULTILINE)


def bump(changelog: str, version: str, date: str) -> tuple[str, str]:
    section_match = SECTION_RE.search(changelog)
    if not section_match:
        sys.exit("CHANGELOG.md has no [Unreleased] section to promote")
    notes = section_match.group("body").strip("\n")

    new_unreleased = "## [Unreleased]\n\n### Added\n- Nothing yet.\n"
    new_section = f"{new_unreleased}\n## [{version}] - {date}\n\n{notes}\n"
    changelog = SECTION_RE.sub(new_section.replace("\\", "\\\\"), changelog, count=1)

    link_match = LINK_RE.search(changelog)
    if not link_match:
        sys.exit("CHANGELOG.md has no [Unreleased] compare link to update")
    previous_link_match = FIRST_VERSION_LINK_RE.search(link_match.group("rest"))
    if previous_link_match:
        previous_version = previous_link_match.group("version")
        new_link = f"[{version}]: {REPO_URL}/compare/v{previous_version}...v{version}\n"
    else:
        new_link = f"[{version}]: {REPO_URL}/releases/tag/v{version}\n"

    new_links = f"[Unreleased]: {REPO_URL}/compare/v{version}...HEAD\n{new_link}"
    changelog = LINK_RE.sub(new_links + link_match.group("rest"), changelog, count=1)

    return changelog, notes


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <version>")
    version = sys.argv[1]
    date = datetime.date.today().isoformat()

    with open(CHANGELOG_PATH, encoding="utf-8") as f:
        changelog = f.read()

    changelog, notes = bump(changelog, version, date)

    with open(CHANGELOG_PATH, "w", encoding="utf-8") as f:
        f.write(changelog)

    with open("release_notes.md", "w", encoding="utf-8") as f:
        f.write(notes + "\n")


if __name__ == "__main__":
    main()
