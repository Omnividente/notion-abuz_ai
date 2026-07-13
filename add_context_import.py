import re
with open("internal/proxy/types.go", "r") as f:
    content = f.read()

if '"context"' not in content:
    content = re.sub(r'import \(\n', r'import (\n\t"context"\n', content)

with open("internal/proxy/types.go", "w") as f:
    f.write(content)
