import re
import os
import glob

test_files = glob.glob("internal/proxy/*_test.go")

for file in test_files:
    with open(file, "r") as f:
        content = f.read()

    # handleAnthropicNonStream
    content = re.sub(
        r'handleAnthropicNonStream\(([^,]+),',
        r'handleAnthropicNonStream(&http.Request{Method: "POST", URL: &url.URL{Path: "/v1/messages"}}, \1,',
        content
    )
    # handleAnthropicStream
    content = re.sub(
        r'handleAnthropicStream\(([^,]+),',
        r'handleAnthropicStream(&http.Request{Method: "POST", URL: &url.URL{Path: "/v1/messages"}}, \1,',
        content
    )
    # streamAnthropicTextResponse
    content = re.sub(
        r'streamAnthropicTextResponse\(([^,]+),',
        r'streamAnthropicTextResponse(&http.Request{Method: "POST", URL: &url.URL{Path: "/v1/messages"}}, \1,',
        content
    )

    with open(file, "w") as f:
        f.write(content)
