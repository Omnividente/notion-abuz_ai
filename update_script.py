import os
import re

def update_file(filename):
    with open(filename, 'r') as f:
        content = f.read()

    # account_api.go
    if "account_api.go" in filename:
        content = re.sub(r'req, err := http\.NewRequest\("POST", NotionAPIBase\+"/loadUserContent", bytes\.NewReader\(\[\]byte\("\{\}"\)\)\)',
                         r'req, err := http.NewRequestWithContext(context.Background(), "POST", NotionAPIBase+"/loadUserContent", bytes.NewReader([]byte("{}")))',
                         content)

    # reverseproxy.go (it uses w and r)
    if "reverseproxy.go" in filename:
        # proxyHTML
        content = re.sub(r'req, err := http\.NewRequest\("GET", targetURL, nil\)',
                         r'req, err := http.NewRequestWithContext(r.Context(), "GET", targetURL, nil)',
                         content)
        # other proxy functions in reverseproxy.go
        content = re.sub(r'req, err := http\.NewRequest\(r\.Method, targetURL, r\.Body\)',
                         r'req, err := http.NewRequestWithContext(r.Context(), r.Method, targetURL, r.Body)',
                         content)
        content = re.sub(r'req, err := http\.NewRequest\(r\.Method, targetURL, nil\)',
                         r'req, err := http.NewRequestWithContext(r.Context(), r.Method, targetURL, nil)',
                         content)

    # notion.go
    # We should add Context to CallOptions
    if "types.go" in filename:
        if "Context context.Context" not in content:
            content = re.sub(r'(type CallOptions struct \{\n)',
                             r'\1\tContext                 context.Context       // downstream request context\n',
                             content)

    with open(filename, 'w') as f:
        f.write(content)

for f in ["internal/proxy/account_api.go", "internal/proxy/reverseproxy.go", "internal/proxy/types.go"]:
    update_file(f)
