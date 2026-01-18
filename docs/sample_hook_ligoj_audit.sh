#!/bin/bash
payload="$(echo "$PAYLOAD" | base64 -d)"
echo "$payload">> ligoj_audit.log
echo "$(echo "$payload"|jq -r '.now') $(echo "$payload"|jq -r '.method') $(echo "$payload"|jq -r '.path') [$(echo "$payload"|jq -r '.user')]" >> ligoj_audit.log

