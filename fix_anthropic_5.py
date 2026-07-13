import re
with open("internal/proxy/anthropic.go", "r") as f:
    content = f.read()

# Add context import
if '"context"' not in content:
    content = re.sub(r'import \(\n', r'import (\n\t"context"\n', content)

# Update the missed replacements for context passing
content = re.sub(
    r'return handleAnthropicStreamWithContract\(w, acc, messages, model, requestID, hasTools, false, "", hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, attachments, outputConfig, session\)',
    r'return handleAnthropicStreamWithContract(ctx, w, acc, messages, model, requestID, hasTools, false, "", hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, attachments, outputConfig, session)',
    content
)
content = re.sub(
    r'return handleAnthropicNonStreamWithContract\(w, acc, messages, model, requestID, hasTools, false, "", hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, attachments, outputConfig, session\)',
    r'return handleAnthropicNonStreamWithContract(ctx, w, acc, messages, model, requestID, hasTools, false, "", hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, attachments, outputConfig, session)',
    content
)

with open("internal/proxy/anthropic.go", "w") as f:
    f.write(content)
