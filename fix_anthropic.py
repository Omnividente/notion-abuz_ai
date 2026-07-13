import re
with open("internal/proxy/anthropic.go", "r") as f:
    content = f.read()

# Instead of passing Context everywhere, we can change the signature of
# handleAnthropicStreamWithContract, handleAnthropicNonStreamWithContract,
# handleResearcherStream, handleResearcherNonStream
# to take `r *http.Request` instead of `w http.ResponseWriter` ...
# Actually, just add ctx context.Context to the parameters.

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

# And streamAnthropicTextResponse
content = re.sub(
    r'func streamAnthropicTextResponse\(w http\.ResponseWriter, acc \*Account, messages \[\]ChatMessage, model, requestID string, hasThinking bool, disableBuiltin bool, outputConfig \*AnthropicOutputConfig, callOpts CallOptions\) error \{',
    r'func streamAnthropicTextResponse(ctx context.Context, w http.ResponseWriter, acc *Account, messages []ChatMessage, model, requestID string, hasThinking bool, disableBuiltin bool, outputConfig *AnthropicOutputConfig, callOpts CallOptions) error {',
    content
)

# Update calls to these
# streamAnthropicTextResponse -> pass ctx
content = re.sub(
    r'streamAnthropicTextResponse\(w, acc, messages, model, requestID, hasThinking, disableBuiltin, outputConfig, callOpts\)',
    r'streamAnthropicTextResponse(ctx, w, acc, messages, model, requestID, hasThinking, disableBuiltin, outputConfig, callOpts)',
    content
)
# handleAnthropicStreamWithContract in handleAnthropicStream
content = re.sub(
    r'return handleAnthropicStreamWithContract\(w, acc, messages, model, requestID, hasTools, false, "", hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, attachments, outputConfig, session\)',
    r'return handleAnthropicStreamWithContract(ctx, w, acc, messages, model, requestID, hasTools, false, "", hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, attachments, outputConfig, session)',
    content
)
# handleAnthropicNonStreamWithContract in handleAnthropicNonStream
content = re.sub(
    r'return handleAnthropicNonStreamWithContract\(w, acc, messages, model, requestID, hasTools, false, "", hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, attachments, outputConfig, session\)',
    r'return handleAnthropicNonStreamWithContract(ctx, w, acc, messages, model, requestID, hasTools, false, "", hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, attachments, outputConfig, session)',
    content
)

# Handle calls from HandleAnthropicMessages
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
content = re.sub(
    r'err = handleAnthropicStreamWithContract\(w, acc, messages, notionModel, requestID, hasTools, isCodingAssistant, mode, hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, attachments, outputConfig, session\)',
    r'err = handleAnthropicStreamWithContract(r.Context(), w, acc, messages, notionModel, requestID, hasTools, isCodingAssistant, mode, hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, attachments, outputConfig, session)',
    content
)
content = re.sub(
    r'err = handleAnthropicNonStreamWithContract\(w, acc, messages, notionModel, requestID, hasTools, isCodingAssistant, mode, hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, attachments, outputConfig, session\)',
    r'err = handleAnthropicNonStreamWithContract(r.Context(), w, acc, messages, notionModel, requestID, hasTools, isCodingAssistant, mode, hasThinking, enableWebSearch, enableWorkspaceSearch, useReadOnlyMode, attachments, outputConfig, session)',
    content
)

# Insert ctx into callOpts inside these functions
content = re.sub(
    r'callOpts := CallOptions\{\n\t\tThinkingBlocks',
    r'callOpts := CallOptions{\n\t\tContext: ctx,\n\t\tThinkingBlocks',
    content
)
content = re.sub(
    r'callOpts := CallOptions\{\n\t\tIsResearcher',
    r'callOpts := CallOptions{\n\t\tContext: ctx,\n\t\tIsResearcher',
    content
)
content = re.sub(
    r'callOpts := CallOptions\{\n\t\tEnableWebSearch',
    r'callOpts := CallOptions{\n\t\tContext: ctx,\n\t\tEnableWebSearch',
    content
)

with open("internal/proxy/anthropic.go", "w") as f:
    f.write(content)
