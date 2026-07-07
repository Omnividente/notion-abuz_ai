jq '.tasks |= map(if .id == "add-tool-call-loss-metrics-proxy-with-test" then .status = "done" else . end)' agent_tasks.json > tmp_tasks.json && mv tmp_tasks.json agent_tasks.json
