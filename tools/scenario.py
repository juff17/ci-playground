"""Open test PRs and release runs in ci-playground for the monitors to watch.

Run it as bin/scenario. Each scenario PR adds its own module under sandbox/
and a switches file at .ci/scenarios/<branch>, so merging one never touches
calc/ and never turns extra jobs on for main. Main only moves through PRs
this script merges after their checks pass.

Commits are built from origin/main with a throwaway index, so the checkout
it runs in, its branch and its working tree are never touched.
"""

import argparse
import json
import os
import random
import re
import string
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
BASE = "main"
HOTSPOT = "sandbox/hotspot.txt"
HEARTBEAT = "sandbox/heartbeat.txt"
SWITCHES = ".ci/scenarios"
SLOTS = 24
WATCH_HELP = "Watch it with: /pr-babysit {url}"


class Fail(Exception):
    """A step failed in a way the user should see; main() prints it and exits 1."""


# ------------------------------------------------------------ commands


def sh(*cmd, input=None, env=None):
    r = subprocess.run(cmd, cwd=ROOT, input=input, env=env, text=True, capture_output=True)
    if r.returncode:
        raise Fail(f"{' '.join(cmd[:3])} failed: {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()


def git(*args, **kw):
    return sh("git", *args, **kw)


_slug = None


def slug():
    """owner/name of the GitHub repo origin points at."""
    global _slug
    if _slug is None:
        _slug = sh("gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
    return _slug


def api(path, method="GET", body=None):
    cmd = ["gh", "api", "-X", method, f"repos/{slug()}/{path}"]
    if body is not None:
        cmd += ["--input", "-"]
    out = sh(*cmd, input=json.dumps(body) if body is not None else None)
    return json.loads(out) if out else None


# ------------------------------------------------------------ scenarios

MODULE_OK = '''"""Scenario {sid}: a helper whose tests pass."""


def clamp(value, low, high):
    """value limited to the range low to high."""
    return max(low, min(value, high))
'''

TEST_OK = '''import unittest

from sandbox.{mod} import clamp


class ClampTest(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 3), 3)
        self.assertEqual(clamp(-1, 0, 3), 0)
        self.assertEqual(clamp(2, 0, 3), 2)
'''

MODULE_BUG = '''"""Scenario {sid}: a helper with an off-by-one bug that its test catches."""


def last_n(values, n):
    """The last n items of values."""
    return values[-n - 1:]
'''

TEST_BUG = '''import unittest

from sandbox.{mod} import last_n


class LastNTest(unittest.TestCase):
    def test_last_n(self):
        self.assertEqual(last_n([1, 2, 3, 4], 2), [3, 4])
        self.assertEqual(last_n(["a", "b"], 1), ["b"])
'''

# "occured" is the typo the reviewer bot's nit points at.
MODULE_REVIEW = '''"""Scenario {sid}: a helper for the reviewer bot to comment on."""


def spread(values):
    """The gap between the largest and smallest value. Raises ValueError if an error occured, as for an empty list."""
    return max(values) - min(values)
'''

TEST_REVIEW = '''import unittest

from sandbox.{mod} import spread


class SpreadTest(unittest.TestCase):
    def test_spread(self):
        self.assertEqual(spread([3, 9, 4]), 6)
'''

CODE = {"ok": (MODULE_OK, TEST_OK), "bug": (MODULE_BUG, TEST_BUG), "review": (MODULE_REVIEW, TEST_REVIEW)}

# kind: (code, switches, what the monitor should report)
KINDS = {
    "happy": ("ok", [], "stage lines, then [pipeline] passed. Merge it (bin/scenario merge N) for [merged]"),
    "failing": ("bug", [], "[failed] check / test. The agent should commit a fix to last_n"),
    "flaky": ("ok", ["flaky"], "[failed] extra / flaky, then a proposed retry that passes"),
    "manual": ("ok", ["manual"], "[manual] extra / approval waits on the approval environment"),
    "slow": ("ok", ["slow {minutes}"], "nothing until [pipeline] after the slow job's minutes"),
    "stuck": ("ok", ["stuck"], "[stuck] extra / stuck (watch with --stuck-after 2)"),
    "behind": ("ok", [], "[behind] once main moves (bin/scenario advance). The agent rebases with no conflicts"),
    "conflict": ("ok", [], "[conflict] once main edits its slot (bin/scenario collide N). The agent resolves sandbox/hotspot.txt"),
    "comments": ("review", [], "[comment] and [review] once the bot posts (bin/scenario review N)"),
    "messy": ("bug", ["flaky", "manual"], "[failed] check / test and extra / flaky, and [manual] extra / approval"),
}

FLEET = ["happy", "failing", "flaky", "manual", "behind", "conflict", "comments", "messy"]

# Release runs on main, as bin/scenario pipeline KIND: (inputs, what pipeline-watch should report)
PIPELINES = {
    "happy": ({"gate": "false"}, "every stage passes, then [pipeline] passed"),
    "gated": ({"gate": "true"}, "[manual] deploy / production waits for approval on production"),
    "failing": ({"gate": "false", "fail_at": "test"}, "[failed] test / unit, then [pipeline] failed"),
    "late-fail": ({"gate": "true", "fail_at": "production"}, "[manual] at production, then [failed] deploy / production once approved"),
    "flaky": ({"gate": "false", "flaky_at": "staging"}, "[failed] deploy / staging (a network error), passes on a re-run"),
    "slow": ({"gate": "false", "slow_minutes": "{minutes}"}, "deploy / staging runs for the given minutes"),
}


def stamp():
    """A short id that sorts by time: base36 seconds and two random letters."""
    n, digits = int(time.time()), ""
    while n:
        n, r = divmod(n, 36)
        digits = (string.digits + string.ascii_lowercase)[r] + digits
    return digits[-5:] + "".join(random.choices(string.ascii_lowercase, k=2))


def module_name(sid):
    return "scn_" + re.sub(r"\W", "_", sid)


def switches_text(branch, switches):
    lines = [f"# Switches for the CI runs of {branch}. See README.md, CI scenarios.", *switches]
    return "\n".join(lines) + "\n"


def scenario_files(kind, sid, branch, minutes=10):
    """The files a scenario PR adds, by path."""
    code, switches, _ = KINDS[kind]
    module, test = CODE[code]
    mod = module_name(sid)
    files = {
        f"sandbox/{mod}.py": module.format(sid=sid, mod=mod),
        f"sandbox/test_{mod}.py": test.format(sid=sid, mod=mod),
    }
    if switches:
        files[f"{SWITCHES}/{branch}"] = switches_text(branch, [s.format(minutes=minutes) for s in switches])
    return files


# ------------------------------------------------------------ hotspot slots

SLOT_LINE = re.compile(r"^slot-(\d+): (.*)$")


def slots(text):
    """{slot number: its value} from hotspot.txt."""
    return {int(m[1]): m[2] for m in map(SLOT_LINE.match, text.splitlines()) if m}


def set_slot(text, slot, value):
    out, hit = [], False
    for line in text.splitlines():
        m = SLOT_LINE.match(line)
        if m and int(m[1]) == slot:
            line, hit = f"slot-{slot:02d}: {value}", True
        out.append(line)
    if not hit:
        raise Fail(f"{HOTSPOT} has no slot {slot}")
    return "\n".join(out) + "\n"


def fresh_hotspot():
    lines = ["# Conflict scenarios claim one slot each and rewrite its line. Keep one line per slot."]
    return "\n".join(lines + [f"slot-{i:02d}: free" for i in range(1, SLOTS + 1)]) + "\n"


def slot_of(branch):
    """The slot a conflict branch claims (scn/conflict-s07-...), or None."""
    m = re.match(r"scn/conflict-s(\d+)-", branch)
    return int(m[1]) if m else None


def pick_slot(hotspot_text, open_branches):
    taken = {slot_of(b) for b in open_branches}
    free = [n for n, v in slots(hotspot_text).items() if v == "free" and n not in taken]
    if not free:
        raise Fail(f"no free slot in {HOTSPOT}; run bin/scenario cleanup --prune")
    return random.choice(free)


# ------------------------------------------------------------ git and GitHub


def fetch_main():
    git("fetch", "-q", "origin", BASE)
    return git("rev-parse", f"origin/{BASE}")


def read(rev, path):
    return git("show", f"{rev}:{path}") + "\n"


def commit(parent, files, message):
    """A commit on parent with files set (None removes one), made with a
    throwaway index so the working tree and current branch are untouched."""
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(d) / "index")}
        git("read-tree", parent, env=env)
        for path, text in files.items():
            if text is None:
                git("update-index", "--force-remove", path, env=env)
            else:
                blob = git("hash-object", "-w", "--stdin", input=text)
                git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        tree = git("write-tree", env=env)
    return git("commit-tree", tree, "-p", parent, "-m", message)


def push(sha, branch):
    git("push", "-q", "origin", f"{sha}:refs/heads/{branch}")


def open_pr(branch, title, body):
    url = sh("gh", "pr", "create", "-R", slug(), "--base", BASE, "--head", branch, "--title", title, "--body", body)
    return int(url.rstrip("/").rsplit("/", 1)[1]), url


def open_prs():
    out = sh("gh", "pr", "list", "-R", slug(), "--state", "open", "--limit", "200",
             "--json", "number,headRefName,title,url")
    return [p for p in json.loads(out) if p["headRefName"].startswith(("scn/", "bump/"))]


def runs_for(sha):
    return api(f"actions/runs?head_sha={sha}&event=pull_request&per_page=50")["workflow_runs"]


def wait_green(sha, what, timeout=900):
    """Wait until every PR workflow run for sha finished; Fail unless all passed."""
    print(f"  waiting for {what}'s checks", end="", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        runs = runs_for(sha)
        if runs and all(r["status"] == "completed" for r in runs):
            print()
            bad = [r for r in runs if r["conclusion"] not in ("success", "skipped", "neutral")]
            if bad:
                raise Fail(f"{what}'s checks did not pass: {bad[0]['html_url']}")
            return
        print(".", end="", flush=True)
        time.sleep(10)
    print()
    raise Fail(f"{what}'s checks took longer than {timeout // 60} minutes")


def merge(number, sha, title):
    # GitHub may still be working out mergeability just after a push.
    for attempt in range(6):
        try:
            api(f"pulls/{number}/merge", "PUT", {"merge_method": "squash", "sha": sha, "commit_title": title})
            return
        except Fail as err:
            if attempt == 5 or "not mergeable" not in str(err).lower():
                raise
            time.sleep(5)


def delete_branch(branch):
    try:
        api(f"git/refs/heads/{branch}", "DELETE")
    except Fail as err:
        # Already gone, as when GitHub deletes merged branches itself.
        if "reference does not exist" not in str(err).lower():
            raise


def move_main(change, title, quiet=False):
    """Move main ahead through a bump PR: change(base) gives the files to set.
    The PR merges once its checks pass. quiet skips main's Release run."""
    base = fetch_main()
    bid = stamp()
    branch = f"bump/{bid}"
    sha = commit(base, change(base, bid), f"{title} ({branch})")
    push(sha, branch)
    number, url = open_pr(branch, f"{title} ({branch})", "Moves main ahead for a scenario test. Opened and merged by bin/scenario.")
    print(f"  opened #{number} {url}")
    try:
        wait_green(sha, f"#{number}")
        merge(number, sha, f"{title} (#{number})" + (" [skip ci]" if quiet else ""))
    except Fail:
        print(f"  left #{number} open; close it with bin/scenario cleanup", file=sys.stderr)
        raise
    delete_branch(branch)
    print(f"  merged #{number} into {BASE}")


# ------------------------------------------------------------ commands


def cmd_new(args):
    out = []
    for _ in range(args.count):
        out.append(new_pr(args.kind, args.minutes))
    for kind, number, url, _branch in out:
        if args.now:
            follow_up(kind, number, args)
    print_table(out)


def new_pr(kind, minutes):
    base = fetch_main()
    sid = f"{kind}-{stamp()}"
    files = {}
    if kind == "conflict":
        slot = pick_slot(read(base, HOTSPOT), [p["headRefName"] for p in open_prs()])
        sid = f"conflict-s{slot:02d}-{stamp()}"
    branch = f"scn/{sid}"
    files.update(scenario_files(kind, sid, branch, minutes))
    if kind == "conflict":
        files[HOTSPOT] = set_slot(read(base, HOTSPOT), slot, f"claimed by {branch}")
    mod = module_name(sid)
    sha = commit(base, files, f"Add {mod} ({kind} scenario)")
    push(sha, branch)
    body = (f"Scenario **{kind}**, opened by `bin/scenario`.\n\n"
            f"Expected: {KINDS[kind][2]}.\n\nIt only adds files under `sandbox/`"
            + (" and its switches file" if any(p.startswith(SWITCHES) for p in files) else "")
            + ", so it is safe to merge once its checks pass.")
    number, url = open_pr(branch, f"Add {mod} ({kind} scenario)", body)
    print(f"opened #{number} {kind}: {url}")
    return kind, number, url, branch


def follow_up(kind, number, args):
    if kind == "behind":
        print(f"moving {BASE} ahead for #{number}")
        cmd_advance(argparse.Namespace(quiet=args.quiet))
    elif kind == "conflict":
        cmd_collide(argparse.Namespace(pr=number, quiet=args.quiet))
    elif kind == "comments":
        cmd_review(argparse.Namespace(pr=number, kind="all"))


def print_table(rows):
    if not rows:
        return
    print()
    for kind, number, url, _ in rows:
        print(f"#{number:<5} {kind:<9} {url}")
        print(f"       expect: {KINDS[kind][2]}")
        print(f"       {WATCH_HELP.format(url=url)}")


def cmd_fleet(args):
    kinds = FLEET + [k for k in args.add if k not in FLEET]
    rows = [new_pr(k, args.minutes) for k in kinds]
    print_table(rows)
    todo = [(k, n) for k, n, _, _ in rows if k in ("behind", "conflict", "comments")]
    if args.now:
        for kind, number in todo:
            follow_up(kind, number, args)
        return
    print("\nAttach the monitors, then trigger the rest:")
    for kind, number in todo:
        print(f"  {follow_cmd(kind, number)}")


def follow_cmd(kind, number):
    return {"behind": "bin/scenario advance", "conflict": f"bin/scenario collide {number}",
            "comments": f"bin/scenario review {number}"}[kind]


def cmd_advance(args):
    def change(base, bid):
        return {HEARTBEAT: f"{bid} {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}\n"}
    move_main(change, "Move main ahead", args.quiet)


def cmd_collide(args):
    branch = api(f"pulls/{args.pr}")["head"]["ref"]
    slot = slot_of(branch)
    if slot is None:
        raise Fail(f"#{args.pr} ({branch}) is not a conflict scenario")
    print(f"editing slot {slot:02d} on {BASE}, which #{args.pr} also edits")

    def change(base, bid):
        return {HOTSPOT: set_slot(read(base, HOTSPOT), slot, f"taken on main by bump/{bid}")}
    move_main(change, f"Take hotspot slot {slot:02d} on main", args.quiet)


def cmd_review(args):
    sh("gh", "workflow", "run", "reviewer-bot.yml", "-R", slug(), "-f", f"pr={args.pr}", "-f", f"kind={args.kind}")
    print(f"reviewer bot posting {args.kind} on #{args.pr}")


def cmd_merge(args):
    pr = api(f"pulls/{args.pr}")
    if pr["state"] != "open":
        raise Fail(f"#{args.pr} is {pr['state']}")
    sha, branch = pr["head"]["sha"], pr["head"]["ref"]
    runs = runs_for(sha)
    if not runs:
        raise Fail(f"#{args.pr} has no CI runs for {sha[:7]} yet")
    waiting = [r["html_url"] for r in runs if r["status"] != "completed"]
    if waiting:
        raise Fail(f"#{args.pr}'s checks are still running: {waiting[0]}")
    bad = [r["html_url"] for r in runs if r["conclusion"] not in ("success", "skipped", "neutral")]
    if bad:
        raise Fail(f"#{args.pr}'s checks did not pass, so it would break {BASE}: {bad[0]}")
    merge(args.pr, sha, f"{pr['title']} (#{args.pr})" + (" [skip ci]" if args.quiet else ""))
    if branch.startswith(("scn/", "bump/")):
        delete_branch(branch)
    print(f"merged #{args.pr} into {BASE}")


def cmd_pipeline(args):
    inputs, expect = PIPELINES[args.kind]
    since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fields = [x for k, v in inputs.items() for x in ("-f", f"{k}={v.format(minutes=args.minutes)}")]
    sh("gh", "workflow", "run", "release.yml", "-R", slug(), "--ref", BASE, *fields)
    for _ in range(12):
        time.sleep(5)
        runs = api(f"actions/workflows/release.yml/runs?event=workflow_dispatch&created={quote('>=' + since)}&per_page=1")["workflow_runs"]
        if runs:
            url = runs[0]["html_url"]
            print(f"started Release ({args.kind}): {url}\n  expect: {expect}\n  Watch it with: /pipeline-watch {url}")
            return
    print(f"started Release ({args.kind}); it has not shown up yet, see https://github.com/{slug()}/actions/workflows/release.yml")


def cmd_list(args):
    prs = open_prs()
    if not prs:
        print("no scenario PRs open")
    for p in prs:
        kind = p["headRefName"].split("/", 1)[1].split("-", 1)[0]
        print(f"#{p['number']:<5} {kind:<9} {p['url']}")


def scenario_paths(rev):
    names = git("ls-tree", "-r", "--name-only", rev).splitlines()
    return [n for n in names
            if (n.startswith(f"{SWITCHES}/") and n != f"{SWITCHES}/README.md")
            or re.match(r"sandbox/(test_)?scn_\w+\.py$", n)]


def cmd_cleanup(args):
    prs = open_prs()
    heads = git("ls-remote", "--heads", "origin").splitlines()
    branches = {line.split("refs/heads/", 1)[1] for line in heads if "refs/heads/scn/" in line or "refs/heads/bump/" in line}
    stray = sorted(branches - {p["headRefName"] for p in prs})
    base = fetch_main()
    prune = scenario_paths(base) if args.prune else []
    reset_hotspot = args.prune and read(base, HOTSPOT) != fresh_hotspot()
    if not (prs or stray or prune or reset_hotspot):
        print("nothing to clean up")
        return
    for p in prs:
        print(f"close #{p['number']} {p['headRefName']}")
    for b in stray:
        print(f"delete branch {b}")
    if prune or reset_hotspot:
        print(f"remove {len(prune)} scenario files from {BASE} and free every hotspot slot, through a PR")
    if not args.yes and input("Go ahead? [y/N] ").strip().lower() != "y":
        print("left as is")
        return
    for p in prs:
        api(f"pulls/{p['number']}", "PATCH", {"state": "closed"})
        delete_branch(p["headRefName"])
    for b in stray:
        delete_branch(b)
    if prune or reset_hotspot:
        def change(base, bid):
            return {**{p: None for p in scenario_paths(base)}, HOTSPOT: fresh_hotspot()}
        move_main(change, "Remove merged scenario files", args.quiet)
    print("cleaned up")


def cmd_setup(args):
    uid = json.loads(sh("gh", "api", "user"))["id"]
    api("environments/staging", "PUT", {})
    api("environments/approval", "PUT", {"reviewers": [{"type": "User", "id": uid}], "prevent_self_review": False})
    api("environments/production", "PUT", {"reviewers": [{"type": "User", "id": uid}], "prevent_self_review": False})
    print("environments ready: staging (no gate), approval and production (wait for you)")


# ------------------------------------------------------------ main


def parser():
    p = argparse.ArgumentParser(prog="bin/scenario", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def quiet(s):
        s.add_argument("--quiet", action="store_true", help="skip main's Release run for anything this merges ([skip ci])")

    s = sub.add_parser("new", help="open scenario PRs of one kind")
    s.add_argument("kind", choices=KINDS)
    s.add_argument("-n", "--count", type=int, default=1)
    s.add_argument("--minutes", type=int, default=10, help="for slow: how long the slow job runs")
    s.add_argument("--now", action="store_true", help="also move main or post the review right away")
    quiet(s)
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("fleet", help="open one PR of each kind at once: " + ", ".join(FLEET))
    s.add_argument("--add", nargs="*", default=[], choices=[k for k in KINDS if k not in FLEET], help="also open these")
    s.add_argument("--minutes", type=int, default=10)
    s.add_argument("--now", action="store_true", help="move main and post reviews right away instead of printing the commands")
    quiet(s)
    s.set_defaults(fn=cmd_fleet)

    s = sub.add_parser("advance", help="move main ahead without conflicts, so open PRs fall behind")
    quiet(s)
    s.set_defaults(fn=cmd_advance)

    s = sub.add_parser("collide", help="edit a conflict PR's hotspot slot on main, so it conflicts")
    s.add_argument("pr", type=int)
    quiet(s)
    s.set_defaults(fn=cmd_collide)

    s = sub.add_parser("review", help="have the reviewer bot comment on a PR")
    s.add_argument("pr", type=int)
    s.add_argument("kind", nargs="?", default="all",
                   choices=["all", "nit", "question", "file", "general", "injection", "request-changes", "approve"])
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("merge", help="squash-merge a PR, only if all its checks passed")
    s.add_argument("pr", type=int)
    quiet(s)
    s.set_defaults(fn=cmd_merge)

    s = sub.add_parser("pipeline", help="start a Release run on main for pipeline-watch")
    s.add_argument("kind", choices=PIPELINES)
    s.add_argument("--minutes", type=int, default=10, help="for slow: how long the staging deploy runs")
    s.set_defaults(fn=cmd_pipeline)

    s = sub.add_parser("list", help="list open scenario and bump PRs")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("cleanup", help="close scenario PRs and delete their branches")
    s.add_argument("--prune", action="store_true", help="also remove merged scenario files from main and free the hotspot")
    s.add_argument("-y", "--yes", action="store_true")
    quiet(s)
    s.set_defaults(fn=cmd_cleanup)

    s = sub.add_parser("setup", help="create the staging, approval and production environments")
    s.set_defaults(fn=cmd_setup)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        args.fn(args)
    except Fail as err:
        sys.exit(f"error: {err}")
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
