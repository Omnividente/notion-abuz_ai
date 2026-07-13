import re
with open("internal/proxy/upload.go", "r") as f:
    content = f.read()

# Add context import
if '"context"' not in content:
    content = re.sub(r'import \(\n', r'import (\n\t"context"\n', content)

# 1. uploadFile
content = re.sub(
    r'req, err := http\.NewRequest\("POST", NotionAPIBase\+endpoint, bytes\.NewReader\(bodyBytes\)\)',
    r'req, err := http.NewRequestWithContext(context.Background(), "POST", NotionAPIBase+endpoint, bytes.NewReader(bodyBytes))',
    content
)

# 2. UploadToS3
content = re.sub(
    r'req, err := http\.NewRequest\("POST", postURL, &buf\)',
    r'req, err := http.NewRequestWithContext(context.Background(), "POST", postURL, &buf)',
    content
)

with open("internal/proxy/upload.go", "w") as f:
    f.write(content)
