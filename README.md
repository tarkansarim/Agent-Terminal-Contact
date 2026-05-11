# AgentTerminalContact

AgentTerminalContact is a thin safety layer for contacting live terminal agents.
It does not replace Codex, Claude, tmux, or `agent-tmux`. It guards the risky
operation: sending text into another live agent chat.

V0 supports tmux-managed sessions only.

```bash
bin/agent-contact send \
  --repo /home/tarkan/Dropbox/work/MyTools/CudaGroomTool2 \
  --provider codex \
  --message "Please report the current issue and verifier."
```

Use `--dry-run` to see whether the target would be accepted without sending:

```bash
bin/agent-contact send --repo /path/to/repo --provider codex --message "..." --dry-run
```

The tool refuses to send when the target session is ambiguous, the pane is not
at an idle empty prompt, or pending user text is visible in the composer.

## Development

Run the tests from the repo root:

```bash
PYTHONPATH=src python -m unittest discover -s tests
python -m compileall -q src tests
```

For package-style local use, install into a project virtualenv:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/agent-contact --help
```
