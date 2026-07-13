import re

with open("internal/proxy/notion.go", "r") as f:
    content = f.read()

# For CallInference, we want to use the context from CallOptions if it exists.
# We also have other NewRequest calls in notion.go that should ideally use a context.
# Let's fix them manually for precision.

# 1. runInferenceTranscript in CallInference
content = re.sub(
    r'req, err := http\.NewRequest\("POST", NotionAPIBase\+"/runInferenceTranscript", bytes\.NewReader\(bodyBytes\)\)',
    r'''ctx := context.Background()
	if opt.Context != nil {
		ctx = opt.Context
	}
	req, err := http.NewRequestWithContext(ctx, "POST", NotionAPIBase+"/runInferenceTranscript", bytes.NewReader(bodyBytes))''',
    content
)

# 2. getAvailableModels in FetchModels
content = re.sub(
    r'req, err := http\.NewRequest\("POST", NotionAPIBase\+"/getAvailableModels", bytes\.NewReader\(body\)\)',
    r'req, err := http.NewRequestWithContext(context.Background(), "POST", NotionAPIBase+"/getAvailableModels", bytes.NewReader(body))',
    content
)

# 3. getAIUsageEligibility in CheckQuota
content = re.sub(
    r'reqV1, err := http\.NewRequest\("POST", NotionAPIBase\+"/getAIUsageEligibility", bytes\.NewReader\(body\)\)',
    r'reqV1, err := http.NewRequestWithContext(context.Background(), "POST", NotionAPIBase+"/getAIUsageEligibility", bytes.NewReader(body))',
    content
)

# 4. getAIUsageEligibilityV2 in CheckQuota
content = re.sub(
    r'reqV2, err := http\.NewRequest\("POST", NotionAPIBase\+"/getAIUsageEligibilityV2", bytes\.NewReader\(body2\)\)',
    r'reqV2, err := http.NewRequestWithContext(context.Background(), "POST", NotionAPIBase+"/getAIUsageEligibilityV2", bytes.NewReader(body2))',
    content
)

# 5. loadUserContent in CheckUserWorkspace
content = re.sub(
    r'req, err := http\.NewRequest\("POST", NotionAPIBase\+"/loadUserContent", bytes\.NewReader\(body\)\)',
    r'req, err := http.NewRequestWithContext(context.Background(), "POST", NotionAPIBase+"/loadUserContent", bytes.NewReader(body))',
    content
)

# 6. runInferenceTranscript in callResearcherInference
content = re.sub(
    r'req, err := http\.NewRequest\("POST", NotionAPIBase\+"/runInferenceTranscript", bytes\.NewReader\(bodyBytes\)\)',
    r'''ctx := context.Background()
	if opt != nil && opt.Context != nil {
		ctx = opt.Context
	}
	req, err := http.NewRequestWithContext(ctx, "POST", NotionAPIBase+"/runInferenceTranscript", bytes.NewReader(bodyBytes))''',
    content
)

with open("internal/proxy/notion.go", "w") as f:
    f.write(content)
