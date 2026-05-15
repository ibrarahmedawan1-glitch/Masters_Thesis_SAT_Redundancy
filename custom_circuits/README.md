# Custom Circuits

Drop professor-supplied `.aag` or binary `.aig` circuits here, then run:

```bash
python3 main.py
```

Select optimizer `9` or `10`, then dataset profile `5` for custom circuits only.

- Use Algorithm `9` for the committed in-memory incremental SAT engine.
- Use Algorithm `10` when the circuit may be hard and you want checkpoint/resume behavior.
