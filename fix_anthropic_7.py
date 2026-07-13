import re
with open("internal/proxy/anthropic.go", "r") as f:
    content = f.read()

# I am going to pass r *http.Request all the way down.
# Let's see the functions:
replacements = [
    (r'func handleAnthropicStreamWithContract\(w http\.ResponseWriter, acc \*Account',
     r'func handleAnthropicStreamWithContract(r *http.Request, w http.ResponseWriter, acc *Account'),
    (r'func handleAnthropicStream\(w http\.ResponseWriter, acc \*Account',
     r'func handleAnthropicStream(r *http.Request, w http.ResponseWriter, acc *Account'),
    (r'func handleAnthropicNonStreamWithContract\(w http\.ResponseWriter, acc \*Account',
     r'func handleAnthropicNonStreamWithContract(r *http.Request, w http.ResponseWriter, acc *Account'),
    (r'func handleAnthropicNonStream\(w http\.ResponseWriter, acc \*Account',
     r'func handleAnthropicNonStream(r *http.Request, w http.ResponseWriter, acc *Account'),
    (r'func handleResearcherStream\(w http\.ResponseWriter, acc \*Account',
     r'func handleResearcherStream(r *http.Request, w http.ResponseWriter, acc *Account'),
    (r'func handleResearcherNonStream\(w http\.ResponseWriter, acc \*Account',
     r'func handleResearcherNonStream(r *http.Request, w http.ResponseWriter, acc *Account'),
    (r'func streamAnthropicTextResponse\(w http\.ResponseWriter, acc \*Account',
     r'func streamAnthropicTextResponse(r *http.Request, w http.ResponseWriter, acc *Account'),
    (r'func streamWebSearch\(w http\.ResponseWriter, flusher http\.Flusher, acc \*Account',
     r'func streamWebSearch(r *http.Request, w http.ResponseWriter, flusher http.Flusher, acc *Account')
]

for old, new in replacements:
    content = re.sub(old, new, content)

# Now fix the calls
# In HandleAnthropicMessages
content = re.sub(r'handleResearcherStream\(w, acc, requestMessages, model, requestID, hasThinking\)',
                 r'handleResearcherStream(r, w, acc, requestMessages, model, requestID, hasThinking)', content)
content = re.sub(r'handleResearcherNonStream\(w, acc, requestMessages, model, requestID, hasThinking\)',
                 r'handleResearcherNonStream(r, w, acc, requestMessages, model, requestID, hasThinking)', content)
content = re.sub(r'handleAnthropicStreamWithContract\(w, acc, requestMessages, model, requestID',
                 r'handleAnthropicStreamWithContract(r, w, acc, requestMessages, model, requestID', content)
content = re.sub(r'handleAnthropicNonStreamWithContract\(w, acc, requestMessages, model, requestID',
                 r'handleAnthropicNonStreamWithContract(r, w, acc, requestMessages, model, requestID', content)

# In handleAnthropicStream
content = re.sub(r'return handleAnthropicStreamWithContract\(w, acc, messages, model, requestID',
                 r'return handleAnthropicStreamWithContract(r, w, acc, messages, model, requestID', content)

# In handleAnthropicNonStream
content = re.sub(r'return handleAnthropicNonStreamWithContract\(w, acc, messages, model, requestID',
                 r'return handleAnthropicNonStreamWithContract(r, w, acc, messages, model, requestID', content)

# streamAnthropicTextResponse call
content = re.sub(r'streamAnthropicTextResponse\(w, acc, messages, model, requestID',
                 r'streamAnthropicTextResponse(r, w, acc, messages, model, requestID', content)

# streamWebSearch call
content = re.sub(r'streamWebSearch\(w, flusher, acc, toolQuery, model, requestID, blockIndex, hasThinking\)',
                 r'streamWebSearch(r, w, flusher, acc, toolQuery, model, requestID, blockIndex, hasThinking)', content)


# Now inject r.Context() into CallOptions
content = re.sub(r'callOpts := CallOptions\{\n',
                 r'callOpts := CallOptions{\n\t\tContext: r.Context(),\n', content)

with open("internal/proxy/anthropic.go", "w") as f:
    f.write(content)
