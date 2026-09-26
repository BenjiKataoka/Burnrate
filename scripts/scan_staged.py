"""Pattern check of staged lines before a commit. Prints counts per pattern, never values.

Run from the repo root: python3 scripts/scan_staged.py
A line that must contain a pattern on purpose (a placeholder) can end with: scan:allow
"""
import re
import subprocess
import sys

PATTERNS = {
    "Clerk secret key": r"sk_(live|test)_[A-Za-z0-9]{16,}",
    "Neon API key": r"napi_[A-Za-z0-9]{16,}",
    "Neon connection string": r"postgres(ql)?://[^\s:/]+:[^\s@]+@",
    "Neon password": r"npg_[A-Za-z0-9]{8,}",
    "Discord webhook": r"discord(app)?\.com/api/webhooks/\d+/[\w-]+",
    "Secret assignment": r"(TOKEN|SECRET|KEY|PASSWORD)\s*=\s*['\"]?[A-Za-z0-9_\-]{16,}",
    "Private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "Oracle OCID": r"ocid1\.[a-z]+\.oc1\.[a-z0-9.-]*[a-z0-9]{20,}",
    "Tailscale IP": r"\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b",
    "Email address": r"[\w.+-]+@(?!example\.com)[\w-]+\.[\w.]+",
}


def added_lines() -> list[str]:
    diff = subprocess.run(["git", "diff", "--cached", "-U0", "--no-color"],
                          capture_output=True, text=True, check=True).stdout
    return [l[1:] for l in diff.splitlines()
            if l.startswith("+") and not l.startswith("+++") and not l.rstrip().endswith("scan:allow")]


def main() -> int:
    lines = added_lines()
    hits = {name: sum(1 for l in lines if re.search(p, l)) for name, p in PATTERNS.items()}
    for name, n in hits.items():
        print(f"{'FOUND' if n else 'ok   '}  {name}: {n}")
    total = sum(hits.values())
    print(f"{len(lines)} added lines scanned, {total} findings")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
