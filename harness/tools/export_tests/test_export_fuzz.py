"""E13: 200 seeded trees mixing every shape; four invariants asserted each time."""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import TIERS, TempDirCase, make_link, structure, walk_files, write, write_structure, load_tool  # noqa: E402

export = load_tool("export")

RANK = {name: index for index, name in enumerate(TIERS)}
LANE_DIRS = ["docs", "docs/deep", "brain", "brain/shared", "tests", "examples"]
LOOSE_DIRS = ["", "harness", "harness/deep"]
TREES = 200


class Generated:
    """One synthetic source tree plus the oracle for every entry."""

    def __init__(self, seed: int, root: Path, links_ok: bool):
        self.rng = random.Random(seed)
        self.root = root
        self.expect = {}  # rel -> ("tier", label) | ("unparseable",) | ("symlink",) | ("drop",)
        self.count = 0
        rng = self.rng
        lanes = {}
        used = []
        for lane in ("docs", "records", "knowledge"):
            if rng.random() < 0.7:
                choice = rng.choice([d for d in LANE_DIRS if d not in used] or LANE_DIRS)
                used.append(choice)
                lanes[lane] = [choice]
        self.lanes = lanes
        self.defaults = {lane: rng.choice(TIERS) for lane in ("identity", "knowledge", "journal", "decisions", "records", "docs")}
        self.unlisted = rng.choice(["internal", "exclude"])
        doc = structure(lanes=lanes, lane_defaults=self.defaults, unlisted=self.unlisted)
        write_structure(root, doc)
        self.record("harness/registry/structure.json", is_md=False)
        self.tier = rng.choice(TIERS)
        self.collab_valid = rng.random() < 0.6
        self.collab = root.parent / "collaborators.yaml"
        if self.collab_valid:
            write(self.collab, "collaborators:\n  - id: a\n    name: A\n    tier_max: 5\n")
        else:
            write(self.collab, "collaborators: []\n")
        if rng.random() < 0.5:
            write(root / ".git" / "HEAD", "ref\n")
            write(root / ".git" / "objects" / "x", "o\n")
        for index in range(rng.randint(5, 25)):
            self.add_entry(index, links_ok)

    def lane_default(self, rel: str):
        best, best_len = None, -1
        for lane, paths in self.lanes.items():
            for lane_path in paths:
                if rel == lane_path or rel.startswith(lane_path + "/"):
                    if len(lane_path) > best_len:
                        best, best_len = lane, len(lane_path)
        if best is not None:
            return self.defaults[best]
        return None if self.unlisted == "exclude" else "internal"

    def record(self, rel: str, is_md: bool, label=None):
        self.count += 1
        if label is None:
            default = self.lane_default(rel)
            self.expect[rel] = ("drop",) if default is None else ("tier", default)
        else:
            self.expect[rel] = ("tier", label)

    def add_entry(self, index: int, links_ok: bool):
        rng = self.rng
        directory = rng.choice(LANE_DIRS + LOOSE_DIRS)
        base = f"{directory}/" if directory else ""
        shape = rng.choice(["labeled", "labeled", "nofm", "bad", "binary", "dotfile", "attachment", "link", "gitfile"])
        if shape == "labeled":
            label = rng.choice(TIERS)
            rel = f"{base}f{index}.md"
            write(self.root / rel, f"---\ntitle: x\naccess: {label}\n---\nbody {index}\n")
            self.record(rel, True, label)
        elif shape == "nofm":
            rel = f"{base}n{index}.md"
            write(self.root / rel, f"plain {index}\n")
            self.record(rel, True)
        elif shape == "bad":
            rel = f"{base}b{index}.md"
            variant = rng.choice(["dup", "bom", "cr", "unknown", "unclosed"])
            body = {
                "dup": b"---\naccess: public\naccess: internal\n---\n",
                "bom": b"\xef\xbb\xbf---\naccess: public\n---\n",
                "cr": b"---\r\naccess: public\r\n---\r\n",
                "unknown": b"---\naccess: mystery\n---\n",
                "unclosed": b"---\naccess: public\nbody without a closing fence\n",
            }[variant]
            write(self.root / rel, body)
            self.count += 1
            self.expect[rel] = ("unparseable",)
        elif shape == "binary":
            rel = f"{base}d{index}.bin"
            write(self.root / rel, rng.randbytes(rng.randint(1, 4096)))
            self.record(rel, False)
        elif shape == "dotfile":
            rel = f"{base}.hidden{index}"
            write(self.root / rel, f"dot {index}\n")
            self.record(rel, False)
        elif shape == "attachment":
            rel = f"{base}a{index}.md"
            label = rng.choice(TIERS)
            target_dir = rng.choice(LANE_DIRS + LOOSE_DIRS)
            target = f"{target_dir}/img{index}.png" if target_dir else f"img{index}.png"
            depth = len([p for p in base.split("/") if p])
            relative = "../" * depth + target
            write(self.root / rel, f"---\naccess: {label}\n---\n![i]({relative})\n")
            self.record(rel, True, label)
            write(self.root / target, b"\x89PNG" + bytes([index % 256]))
            self.record(target, False)
        elif shape == "link":
            if not links_ok:
                return
            target = self.root / f"{base}t{index}.txt"
            write(target, f"target {index}\n")
            self.record(target.relative_to(self.root).as_posix(), False)
            rel = f"{base}l{index}.txt"
            if make_link(target, self.root / rel):
                self.count += 1
                self.expect[rel] = ("symlink",)
        elif shape == "gitfile":
            write(self.root / base / ".git", "gitdir: elsewhere\n") if base else write(self.root / "harness" / ".git", "gitdir\n")


class TestFuzz(TempDirCase):
    def test_e13_invariants_over_200_trees(self):
        probe_target = self.tmp / "probe-target"
        probe_target.mkdir()
        links_ok = make_link(probe_target, self.tmp / "probe-link")
        refused = 0
        for seed in range(TREES):
            case = self.tmp / f"case{seed}"
            src = case / "src"
            src.mkdir(parents=True)
            gen = Generated(seed, src, links_ok)
            out = case / "out"
            expects_refusal = RANK[gen.tier] >= RANK["restricted"] and not gen.collab_valid
            try:
                result = export.export_tree(src, out, gen.tier, gen.collab)
            except export.Refused as exc:
                assert expects_refusal, f"seed {seed}: unexpected refusal {exc}"
                assert not out.exists(), f"seed {seed}: refusal wrote a destination"
                refused += 1
                continue
            assert not expects_refusal, f"seed {seed}: restricted export ran without collaborators"
            self.check(seed, gen, out, result)
        assert refused > 0, "no seed exercised the restricted gate"

    def check(self, seed: int, gen: Generated, out: Path, result: dict):
        requested = RANK[gen.tier]
        present = walk_files(out)
        for rel in present:
            assert ".git" not in Path(rel).parts, f"seed {seed}: .git in destination ({rel})"
            oracle = gen.expect.get(rel)
            assert oracle is not None, f"seed {seed}: unknown file in destination {rel}"
            assert oracle[0] == "tier", f"seed {seed}: {rel} is {oracle[0]} but was copied"
            assert oracle[1] != "secret", f"seed {seed}: secret file {rel} exported"
            assert RANK[oracle[1]] <= requested, f"seed {seed}: {rel} at {oracle[1]} above {gen.tier}"
        for rel, oracle in gen.expect.items():
            if oracle[0] == "tier" and oracle[1] != "secret" and RANK[oracle[1]] <= requested:
                assert rel in present, f"seed {seed}: {rel} at {oracle[1]} missing from a {gen.tier} export"
        assert not (out / ".git").exists()
        counted = len(result["copied"]) + len(result["excluded"]) + len(result["unparseable"]) + len(result["symlinks"])
        assert counted == result["input_files"], f"seed {seed}: counts {counted} != input {result['input_files']}"
        assert result["input_files"] == gen.count, f"seed {seed}: tool saw {result['input_files']} files, generator wrote {gen.count}"
        assert result["input_files"] == len(walk_files(gen.root)), f"seed {seed}: walk disagrees"
        expected_unparseable = sum(1 for o in gen.expect.values() if o[0] == "unparseable")
        assert len(result["unparseable"]) == expected_unparseable, f"seed {seed}: unparseable count"
        expected_links = sum(1 for o in gen.expect.values() if o[0] == "symlink")
        assert len(result["symlinks"]) == expected_links, f"seed {seed}: symlink count"
        assert len(result["copied"]) == len(present), f"seed {seed}: copied count vs destination"
