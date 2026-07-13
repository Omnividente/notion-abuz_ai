import re
with open("internal/proxy/notion.go", "r") as f:
    content = f.read()

if '"context"' not in content:
    content = re.sub(r'import \(\n', r'import (\n\t"context"\n', content)
    with open("internal/proxy/notion.go", "w") as f:
        f.write(content)

with open("internal/proxy/upload.go", "r") as f:
    content = f.read()

content = re.sub(r'\t"context"\n', "", content)
content = re.sub(r'req, err := http\.NewRequestWithContext\(context\.Background\(\)', r'req, err := http.NewRequest(', content)
with open("internal/proxy/upload.go", "w") as f:
    f.write(content)
