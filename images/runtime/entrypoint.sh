#!/bin/sh
# Apply the network conditions of the testbed (delay, jitter, loss) to this container's
# interface, then start the real command. Needs the NET_ADMIN capability, which mcpnet
# adds only to containers that have conditions set.
set -e
if [ -n "$MCPNET_DELAY_MS$MCPNET_LOSS_PCT" ]; then
  args=""
  [ -n "$MCPNET_DELAY_MS" ] && args="delay ${MCPNET_DELAY_MS}ms ${MCPNET_JITTER_MS:-0}ms"
  [ -n "$MCPNET_LOSS_PCT" ] && args="$args loss ${MCPNET_LOSS_PCT}%"
  for dev in $(ip -o link show | awk -F': ' '{print $2}' | cut -d@ -f1 | grep '^eth'); do
    tc qdisc replace dev "$dev" root netem $args
    echo "mcpnet: $dev netem $args"
  done
fi
exec "$@"
