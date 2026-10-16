#!/bin/sh
# Apply the network conditions of the testbed (delay, jitter, loss) to this container's
# interface, then start the real command. Needs the NET_ADMIN capability, which mcp-cybernet-lab
# adds only to containers that have conditions set.
set -e
if [ -n "$MCL_DELAY_MS$MCL_LOSS_PCT" ]; then
  args=""
  [ -n "$MCL_DELAY_MS" ] && args="delay ${MCL_DELAY_MS}ms ${MCL_JITTER_MS:-0}ms"
  [ -n "$MCL_LOSS_PCT" ] && args="$args loss ${MCL_LOSS_PCT}%"
  for dev in $(ip -o link show | awk -F': ' '{print $2}' | cut -d@ -f1 | grep '^eth'); do
    tc qdisc replace dev "$dev" root netem $args
    echo "mcl: $dev netem $args"
  done
fi
exec "$@"
