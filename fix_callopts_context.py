import re

with open("internal/proxy/anthropic.go", "r") as f:
    content = f.read()

# Add r.Context() to callOpts where appropriate
# In anthropic.go, we are inside a http.Handler func (w http.ResponseWriter, r *http.Request)
# We can just add Context: r.Context(), to CallOptions{}

content = re.sub(
    r'callOpts := CallOptions\{\n',
    r'callOpts := CallOptions{\n\t\tContext: r.Context(),\n',
    content
)

with open("internal/proxy/anthropic.go", "w") as f:
    f.write(content)
