"""Guard against accidental credential commits; intentionally narrow, no network."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", "__pycache__", ".pytest_cache", "dist", "build"}
SECRET_PATTERNS = [
    re.compile(r"(?i)AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)(?:api[_-]?token|secret[_-]?key|password)\s*[:=]\s*['\"]?(?!\$\{|<|your_|change_me|example|)[A-Za-z0-9_\-/.+=]{24,}"),
]
BLOCKED_FILENAMES = {".env", ".env.production", "credentials.json", "service-account.json"}
violations = []
for path in ROOT.rglob("*"):
    if any(part in EXCLUDED for part in path.parts):
        continue
    if not path.is_file():
        continue
    if path.name in BLOCKED_FILENAMES:
        violations.append(f"forbidden credential file: {path.relative_to(ROOT)}")
        continue
    if path.suffix.lower() not in {".py", ".yaml", ".yml", ".json", ".md", ".txt", ".toml", ".ini", ".html", ".js", ".sql", ".sh", ".bat", ".env"}:
        continue
    try:
        data = path.read_text(encoding="utf-8")
    except (UnicodeError, OSError):
        continue
    if path.name == ".env.example":
        # Examples may contain empty/template values, which are expected.
        continue
    for pattern in SECRET_PATTERNS[:2]:
        if pattern.search(data):
            violations.append(f"secret-like value: {path.relative_to(ROOT)} ({pattern.pattern})")
            break
if violations:
    print("Potential secrets found; review before pushing:")
    print("\n".join(violations))
    sys.exit(1)
print("Secret hygiene check passed: no obvious private-key/AWS-key patterns or live .env files found.")
