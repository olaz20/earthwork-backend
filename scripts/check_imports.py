"""Checks every `app` import in the project without running the app.

    python scripts/check_imports.py            (from the project root, the folder that contains app/)

Reports: imported modules that do not exist, imported names that the target module does not
define, and circular imports. Fix what it prints, run it again, repeat until it says OK.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def module_file(name: str) -> Path | None:
    base = ROOT.joinpath(*name.split("."))
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    if base.is_dir():
        return base  # namespace package
    return None


def top_level_names(path: Path) -> set[str]:
    """Names a module defines or re-exports at import time."""
    if path.is_dir():
        return set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()

    def visit(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    for n in ast.walk(t):
                        if isinstance(n, ast.Name):
                            names.add(n.id)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    names.add((a.asname or a.name).split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    names.add(a.asname or a.name)
            elif isinstance(node, (ast.If, ast.Try)):
                for block in ("body", "orelse", "finalbody"):
                    visit(getattr(node, block, []))
                for h in getattr(node, "handlers", []):
                    visit(h.body)

    visit(tree.body)
    return names


def resolve_from(node: ast.ImportFrom, current: str, is_pkg: bool) -> str | None:
    if node.level == 0:
        return node.module
    parts = current.split(".")
    base = parts if is_pkg else parts[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


def main() -> int:
    if not APP.is_dir():
        print(f"cannot find {APP}; run this from the project root")
        return 2
    problems: list[str] = []
    graph: dict[str, set[str]] = {}

    for path in sorted(APP.rglob("*.py")):
        current = module_name(path)
        is_pkg = path.name == "__init__.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(ROOT)
        graph.setdefault(current, set())

        # imports executed at import time = module level (not inside functions/classes)
        def module_level(body):
            for n in body:
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    yield n, True
                elif isinstance(n, ast.If):
                    # `if TYPE_CHECKING:` blocks never run, so they cannot cause cycles
                    typing_only = "TYPE_CHECKING" in ast.dump(n.test)
                    for sub, _ in module_level(n.body + n.orelse):
                        yield sub, not typing_only
                elif isinstance(n, ast.Try):
                    yield from module_level(n.body + [x for h in n.handlers for x in h.body] + n.orelse)

        for node, runs in module_level(tree.body):
            if isinstance(node, ast.Import):
                targets = [(a.name, None) for a in node.names if a.name.split(".")[0] == "app"]
            else:
                mod = resolve_from(node, current, is_pkg)
                if not mod or mod.split(".")[0] != "app":
                    continue
                targets = [(mod, a.name) for a in node.names]

            for mod, name in targets:
                target = module_file(mod)
                if target is None:
                    problems.append(f"{rel}:{node.lineno}: module '{mod}' does not exist")
                    continue
                if runs:
                    graph[current].add(mod)
                if name is None or name == "*":
                    continue
                if name in top_level_names(target) or module_file(f"{mod}.{name}"):
                    if module_file(f"{mod}.{name}") and runs:
                        graph[current].add(f"{mod}.{name}")
                    continue
                problems.append(
                    f"{rel}:{node.lineno}: '{name}' is not defined in {mod} "
                    f"({target.relative_to(ROOT)})"
                )

    # circular imports (module level only)
    seen: dict[str, int] = {}
    stack: list[str] = []

    def dfs(m: str):
        seen[m] = 1
        stack.append(m)
        for n in sorted(graph.get(m, ())):
            if n not in graph:
                continue
            if seen.get(n) == 1:
                cycle = stack[stack.index(n):] + [n]
                problems.append("circular import: " + " -> ".join(cycle))
            elif n not in seen:
                dfs(n)
        stack.pop()
        seen[m] = 2

    for m in sorted(graph):
        if m not in seen:
            dfs(m)

    if problems:
        print(f"{len(problems)} problem(s):\n")
        print("\n".join(dict.fromkeys(problems)))
        return 1
    print(f"OK: all app imports resolve and there are no circular imports ({len(graph)} modules checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
