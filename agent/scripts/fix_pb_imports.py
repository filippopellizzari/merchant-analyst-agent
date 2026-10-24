"""Post-process the protoc output under merchant_analyst/pb.

protoc emits `from merchant.v1 import analyst_pb2 ...` in the *_grpc.py file, which assumes
`merchant` is a top-level package. We vendor the stubs under `merchant_analyst.pb`, so the
import is rewritten to the package-correct form and `__init__.py` files are created so that

    from merchant_analyst.pb.merchant.v1 import analyst_pb2, analyst_pb2_grpc

works. Idempotent: safe to run after every regeneration.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
PB_DIR = AGENT_DIR / "merchant_analyst" / "pb"
PACKAGE_PREFIX = "merchant_analyst.pb"

# `from merchant.v1 import analyst_pb2 as ...` -> `from merchant_analyst.pb.merchant.v1 import ...`
IMPORT_RE = re.compile(r"^from (merchant(?:\.[\w]+)*) import ", re.MULTILINE)


def rewrite_imports(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        pkg = match.group(1)
        if pkg.startswith(PACKAGE_PREFIX):
            return match.group(0)
        return f"from {PACKAGE_PREFIX}.{pkg} import "

    return IMPORT_RE.sub(repl, text)


def ensure_init_files(root: Path) -> list[Path]:
    created: list[Path] = []
    for directory in [root, *sorted(p for p in root.rglob("*") if p.is_dir())]:
        if directory.name == "__pycache__":
            continue
        init = directory / "__init__.py"
        if not init.exists():
            init.write_text("")
            created.append(init)
    return created


def main() -> int:
    if not PB_DIR.exists():
        print(f"error: {PB_DIR} does not exist; run protoc first", file=sys.stderr)
        return 1
    changed = 0
    for path in PB_DIR.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        original = path.read_text()
        updated = rewrite_imports(original)
        if updated != original:
            path.write_text(updated)
            changed += 1
            print(f"rewrote imports in {path.relative_to(AGENT_DIR)}")
    for init in ensure_init_files(PB_DIR):
        print(f"created {init.relative_to(AGENT_DIR)}")
    print(f"done: {changed} file(s) rewritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
