import re
with open("internal/proxy/anthropic.go", "r") as f:
    content = f.read()

# Add context import
if '"context"' not in content:
    content = re.sub(r'import \(\n', r'import (\n\t"context"\n', content)

# Remove the bad undefined ctx in performToolSearch (line 265). It doesn't have ctx parameter
content = re.sub(
    r'callOpts := CallOptions\{\n\t\tContext: ctx,\n\t\tEnableWebSearch',
    r'callOpts := CallOptions{\n\t\tEnableWebSearch',
    content
)
# Actually performToolSearch does not have ctx. Let's find performToolSearch signature
content = re.sub(
    r'func performToolSearch\(w http\.ResponseWriter, acc \*Account, flusher http\.Flusher, blockIndex \*int, query, requestID string, outputConfig \*AnthropicOutputConfig\) error \{',
    r'func performToolSearch(ctx context.Context, w http.ResponseWriter, acc *Account, flusher http.Flusher, blockIndex *int, query, requestID string, outputConfig *AnthropicOutputConfig) error {',
    content
)
# We need to add ctx back for performToolSearch body, but wait it has Context: ctx now. Let's fix line 265
content = re.sub(
    r'callOpts := CallOptions\{\n\t\tEnableWebSearch',
    r'callOpts := CallOptions{\n\t\tContext: ctx,\n\t\tEnableWebSearch',
    content
)

# Call to performToolSearch
content = re.sub(
    r'err := performToolSearch\(w, acc, flusher, blockIndex, toolQuery, requestID, outputConfig\)',
    r'err := performToolSearch(ctx, w, acc, flusher, blockIndex, toolQuery, requestID, outputConfig)',
    content
)


# Fix lines 1266 / 1268 - handleResearcherStream/NonStream calls which we missed
content = re.sub(
    r'err = handleResearcherStream\(w, acc, messages, notionModel, requestID, hasThinking\)',
    r'err = handleResearcherStream(r.Context(), w, acc, messages, notionModel, requestID, hasThinking)',
    content
)
content = re.sub(
    r'err = handleResearcherNonStream\(w, acc, messages, notionModel, requestID, hasThinking\)',
    r'err = handleResearcherNonStream(r.Context(), w, acc, messages, notionModel, requestID, hasThinking)',
    content
)

with open("internal/proxy/anthropic.go", "w") as f:
    f.write(content)
