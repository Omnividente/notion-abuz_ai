import re
import os

files = [
    "internal/proxy/notion.go",
    "internal/proxy/account_api.go",
    "internal/proxy/reverseproxy.go",
    "internal/proxy/upload.go",
]

for file in files:
    with open(file, "r") as f:
        content = f.read()

    if '"context"' not in content:
        content = re.sub(r'import \(\n', r'import (\n\t"context"\n', content)
        with open(file, "w") as f:
            f.write(content)
