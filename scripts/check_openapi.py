"""Проверяет контракт: YAML читается, все $ref ведут на существующие схемы."""

import re
import sys

import yaml

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
spec = yaml.safe_load(text)

errors = []
if not str(spec.get("openapi", "")).startswith("3."):
    errors.append("поле openapi должно быть версии 3.x")
if not spec.get("paths"):
    errors.append("нет paths")

for section, name in sorted(set(re.findall(r"\$ref:\s*'#/components/(\w+)/(\w+)'", text))):
    if name not in spec.get("components", {}).get(section, {}):
        errors.append(f"битая ссылка: #/components/{section}/{name}")

for route in spec.get("paths", {}):
    if not route.startswith("/"):
        errors.append(f"путь без ведущего /: {route}")

if errors:
    print("\n".join(errors))
    sys.exit(1)
print(f"OK: {len(spec['paths'])} путей, ссылки целы")
