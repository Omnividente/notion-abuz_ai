import re
import glob

test_files = glob.glob("internal/proxy/*_test.go")

for file in test_files:
    with open(file, "r") as f:
        content = f.read()

    # Check if we injected url.URL, if so, we need import "net/url"
    if "url.URL{" in content and '"net/url"' not in content:
        content = re.sub(r'import \(\n', r'import (\n\t"net/url"\n', content)

    with open(file, "w") as f:
        f.write(content)
