import re
with open("internal/proxy/anthropic.go", "r") as f:
    content = f.read()

# Add context import
if '"context"' not in content:
    content = re.sub(r'import \(\n', r'import (\n\t"context"\n', content)

# Instead of modifying 10 functions, let's just pass `r.Context()` to the outermost handler
# and thread it through.
# Let's find HandleAnthropicMessages and modify where we can get context.
