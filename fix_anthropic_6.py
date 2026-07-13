import re
with open("internal/proxy/anthropic.go", "r") as f:
    content = f.read()

content = re.sub(
    r'callOpts := CallOptions\{\n\t\tThinkingBlocks:',
    r'callOpts := CallOptions{\n\t\tContext: ctx,\n\t\tThinkingBlocks:',
    content
)

content = re.sub(
    r'callOpts := CallOptions\{\n\t\tIsResearcher:',
    r'callOpts := CallOptions{\n\t\tContext: ctx,\n\t\tIsResearcher:',
    content
)

with open("internal/proxy/anthropic.go", "w") as f:
    f.write(content)
