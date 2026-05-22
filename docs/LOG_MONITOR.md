# Log monitor & Cursor agent loop

Watches `logs/app.jsonl`, `logs/server.log`, and `logs/frontend.log` for new errors and wakes the Cursor agent using the [loop skill](https://cursor.com) dynamic schedule.

## Sentinel (Cursor-monitored shell)

```
AGENT_LOOP_WAKE_logmonitor {"prompt":"...","reason":"...","cooldown_secs":120}
```

- **Regex for agent notifications:** `^AGENT_LOOP_WAKE_logmonitor`
- **Must run attached to a Cursor background shell** (stdout). Detached `nohup` logs to `/tmp` only; it does not wake the IDE agent.

## Commands

| Command | Purpose |
|---------|---------|
| `./scripts/log-monitor-loop.sh cursor-loop` | **Cursor path** — dynamic watcher + 10m heartbeat on stdout |
| `./scripts/log-monitor-loop.sh start` | Detached watcher (survives IDE restarts); log at `/tmp/ai-copilot-log-monitor.log` |
| `./scripts/log-monitor-loop.sh once` | Single scan |
| `./scripts/log-monitor-loop.sh stop` | Stop all modes |
| `./scripts/log-monitor-loop.sh status` | PIDs and cooldown state |

## Cooldown

Default **120s** between wakes (shared across watch + heartbeat). Override:

```bash
COOLDOWN_SECS=180 ./scripts/log-monitor-loop.sh cursor-loop
```

## Arming in Cursor (agent)

1. Run the log review prompt once immediately.
2. Start a **background shell** titled `Loop dynamic: log monitor`:

   ```bash
   cd "/Users/imac/Documents/AI Apps/AI_Copilot"
   ./scripts/log-monitor-loop.sh cursor-loop
   ```

3. Use monitored output matching `^AGENT_LOOP_WAKE_logmonitor`.
4. On each wake, read the JSON `prompt` from the latest matching line and execute it.
5. Optional: also run `./scripts/log-monitor-loop.sh start` for durable off-IDE logging.

## User `/loop` shorthand

Equivalent intent:

```
/loop Review AI Copilot logs for new errors in logs/app.jsonl, logs/server.log, logs/frontend.log
```

Then arm `cursor-loop` as the event-driven watcher per the loop skill **Dynamic Schedule**.

## Stop

```bash
./scripts/log-monitor-loop.sh stop
```

Kill the Cursor background shell task if it is still running.
