import re
with open("internal/proxy/anthropic.go", "r") as f:
    content = f.read()

# Instead of passing the context through 10 layers, we can just use r.Context() in HandleAnthropicMessages
# wait, HandleAnthropicMessages doesn't do the CallInference.
# To pass the context to CallInference, we must pass it into CallOptions.
# Let's add Context context.Context to the parameters of the handle functions.

content = re.sub(
    r'func handleAnthropicStreamWithContract\(w http\.ResponseWriter, acc \*Account, messages \[\]ChatMessage, model, requestID string, hasTools bool, isCodingAssistant bool, mode string, hasThinking bool, enableWebSearch bool, enableWorkspaceSearch \*bool, useReadOnlyMode bool, attachments \[\]UploadedAttachment, outputConfig \*AnthropicOutputConfig, session \*Session\) error \{',
    r'func handleAnthropicStreamWithContract(ctx context.Context, w http.ResponseWriter, acc *Account, messages []ChatMessage, model, requestID string, hasTools bool, isCodingAssistant bool, mode string, hasThinking bool, enableWebSearch bool, enableWorkspaceSearch *bool, useReadOnlyMode bool, attachments []UploadedAttachment, outputConfig *AnthropicOutputConfig, session *Session) error {',
    content
)
content = re.sub(
    r'func handleAnthropicStream\(w http\.ResponseWriter, acc \*Account, messages \[\]ChatMessage, model, requestID string, hasTools bool, hasThinking bool, enableWebSearch bool, enableWorkspaceSearch \*bool, useReadOnlyMode bool, attachments \[\]UploadedAttachment, outputConfig \*AnthropicOutputConfig, session \*Session\) error \{',
    r'func handleAnthropicStream(ctx context.Context, w http.ResponseWriter, acc *Account, messages []ChatMessage, model, requestID string, hasTools bool, hasThinking bool, enableWebSearch bool, enableWorkspaceSearch *bool, useReadOnlyMode bool, attachments []UploadedAttachment, outputConfig *AnthropicOutputConfig, session *Session) error {',
    content
)
content = re.sub(
    r'func handleAnthropicNonStreamWithContract\(w http\.ResponseWriter, acc \*Account, messages \[\]ChatMessage, model, requestID string, hasTools bool, isCodingAssistant bool, mode string, hasThinking bool, enableWebSearch bool, enableWorkspaceSearch \*bool, useReadOnlyMode bool, attachments \[\]UploadedAttachment, outputConfig \*AnthropicOutputConfig, session \*Session\) error \{',
    r'func handleAnthropicNonStreamWithContract(ctx context.Context, w http.ResponseWriter, acc *Account, messages []ChatMessage, model, requestID string, hasTools bool, isCodingAssistant bool, mode string, hasThinking bool, enableWebSearch bool, enableWorkspaceSearch *bool, useReadOnlyMode bool, attachments []UploadedAttachment, outputConfig *AnthropicOutputConfig, session *Session) error {',
    content
)
content = re.sub(
    r'func handleAnthropicNonStream\(w http\.ResponseWriter, acc \*Account, messages \[\]ChatMessage, model, requestID string, hasTools bool, hasThinking bool, enableWebSearch bool, enableWorkspaceSearch \*bool, useReadOnlyMode bool, attachments \[\]UploadedAttachment, outputConfig \*AnthropicOutputConfig, session \*Session\) error \{',
    r'func handleAnthropicNonStream(ctx context.Context, w http.ResponseWriter, acc *Account, messages []ChatMessage, model, requestID string, hasTools bool, hasThinking bool, enableWebSearch bool, enableWorkspaceSearch *bool, useReadOnlyMode bool, attachments []UploadedAttachment, outputConfig *AnthropicOutputConfig, session *Session) error {',
    content
)
content = re.sub(
    r'func handleResearcherStream\(w http\.ResponseWriter, acc \*Account, messages \[\]ChatMessage, model, requestID string, hasThinking bool\) error \{',
    r'func handleResearcherStream(ctx context.Context, w http.ResponseWriter, acc *Account, messages []ChatMessage, model, requestID string, hasThinking bool) error {',
    content
)
content = re.sub(
    r'func handleResearcherNonStream\(w http\.ResponseWriter, acc \*Account, messages \[\]ChatMessage, model, requestID string, hasThinking bool\) error \{',
    r'func handleResearcherNonStream(ctx context.Context, w http.ResponseWriter, acc *Account, messages []ChatMessage, model, requestID string, hasThinking bool) error {',
    content
)
content = re.sub(
    r'func streamAnthropicTextResponse\(w http\.ResponseWriter, acc \*Account, messages \[\]ChatMessage, model, requestID string, hasThinking bool, disableBuiltin bool, outputConfig \*AnthropicOutputConfig, callOpts CallOptions\) error \{',
    r'func streamAnthropicTextResponse(ctx context.Context, w http.ResponseWriter, acc *Account, messages []ChatMessage, model, requestID string, hasThinking bool, disableBuiltin bool, outputConfig *AnthropicOutputConfig, callOpts CallOptions) error {',
    content
)

# Update calls in HandleAnthropicMessages
content = re.sub(
    r'reqErr = handleResearcherStream\(w, acc, requestMessages, model, requestID, hasThinking\)',
    r'reqErr = handleResearcherStream(r.Context(), w, acc, requestMessages, model, requestID, hasThinking)',
    content
)
content = re.sub(
    r'reqErr = handleResearcherNonStream\(w, acc, requestMessages, model, requestID, hasThinking\)',
    r'reqErr = handleResearcherNonStream(r.Context(), w, acc, requestMessages, model, requestID, hasThinking)',
    content
)
content = re.sub(
    r'reqErr = handleAnthropicStreamWithContract\(w, acc, requestMessages, model, requestID, hasTools, isCodingAssistant, req\.Mode, hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, uploadedAttachments, req\.OutputConfig, currentSession\)',
    r'reqErr = handleAnthropicStreamWithContract(r.Context(), w, acc, requestMessages, model, requestID, hasTools, isCodingAssistant, req.Mode, hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, uploadedAttachments, req.OutputConfig, currentSession)',
    content
)
content = re.sub(
    r'reqErr = handleAnthropicNonStreamWithContract\(w, acc, requestMessages, model, requestID, hasTools, isCodingAssistant, req\.Mode, hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, uploadedAttachments, req\.OutputConfig, currentSession\)',
    r'reqErr = handleAnthropicNonStreamWithContract(r.Context(), w, acc, requestMessages, model, requestID, hasTools, isCodingAssistant, req.Mode, hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, uploadedAttachments, req.OutputConfig, currentSession)',
    content
)

# Update calls in handleAnthropicStream / NonStream
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

# streamAnthropicTextResponse usage
content = re.sub(
    r'streamAnthropicTextResponse\(w, acc, messages, model, requestID, hasThinking, disableBuiltin, outputConfig, callOpts\)',
    r'streamAnthropicTextResponse(ctx, w, acc, messages, model, requestID, hasThinking, disableBuiltin, outputConfig, callOpts)',
    content
)

# Set ctx in CallOptions inside these handle... functions
# 1. handleAnthropicStreamWithContract
content = re.sub(
    r'callOpts := CallOptions\{\n\t\tThinkingBlocks:',
    r'callOpts := CallOptions{\n\t\tContext: ctx,\n\t\tThinkingBlocks:',
    content
)

# 2. handleAnthropicNonStreamWithContract
# Wait, handleAnthropicStreamWithContract and handleAnthropicNonStreamWithContract both use this structure.
# Just doing re.sub globally on "callOpts := CallOptions{\n\t\tThinkingBlocks:" might work for both.

# 3. handleResearcherStream
content = re.sub(
    r'callOpts := CallOptions\{\n\t\tIsResearcher:',
    r'callOpts := CallOptions{\n\t\tContext: ctx,\n\t\tIsResearcher:',
    content
)

# 4. handleResearcherNonStream (has ThinkingBlocks but no IsResearcher on line 1)
# Actually handleResearcherNonStream does: callOpts := CallOptions{\n\t\tIsResearcher: true,\n\t\tThinkingBlocks: &thinkingBlocks,
# Wait, both researcher streams have IsResearcher on first line. So the previous sub should catch it.

with open("internal/proxy/anthropic.go", "w") as f:
    f.write(content)
