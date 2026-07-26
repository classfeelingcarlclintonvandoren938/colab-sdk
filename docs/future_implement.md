# Future Implementation — Deferred Features

> Features intentionally deferred from MVP. Each section describes the problem,
> an API sketch, and the technical challenges involved.
>
> These are **not** promises — only candidates for future exploration.
> No feature here has an approved design. Each needs its own ADR before implementation.

---

## Tier 1 — High Priority

Features users will ask for immediately after MVP. Technically feasible on Colab.

---

### 1. `@app.cls()` — Stateful Classes

**Problem:** Users want stateful services on the VM — a class whose methods are individual remote calls, sharing state across calls.

**API Sketch:**

```python
app = App(gpu="T4")

@app.cls
class Model:
    def __init__(self):
        import torch
        self.model = torch.nn.Linear(10, 1)

    def train(self, epochs: int):
        ...

    def predict(self, x: list[float]) -> float:
        ...

# Usage
model = Model.remote()       # Instantiate on VM
model.train.remote(epochs=5) # Call a method
result = model.predict.remote([0.1] * 10)
```

**Challenges:**
- State management — instance lives in memory on the VM; if the session dies, state is lost
- Serialization — method arguments must be JSON-serializable (same constraint as functions)
- Lifecycle — when does the instance get cleaned up? Needs explicit `model.stop()` or GC
- Thread safety — multiple `.remote()` calls on the same instance could race

**Dependencies:**
- None — can be built on top of existing `colab exec` and runner.py pattern

---

### 2. `fn.spawn()` / Future — Non-blocking Execution

**Problem:** `.remote()` blocks until the function completes. Users want fire-and-forget execution with a handle to poll or get the result later.

**API Sketch:**

```python
future = train.spawn(epochs=10)  # Returns immediately
# ... do other work ...
result = future.get(timeout=300)  # Blocks until done

# Or with callback:
future = train.spawn(epochs=10)
future.add_done_callback(lambda r: print(f"Done: {r}"))
```

**Challenges:**
- Background thread on the client to manage concurrent execution
- `colab exec` blocks until completion — multiple `.spawn()` calls would need separate threads or a queue
- Colab CLI doesn't support concurrent execution on the same session natively
- Result storage — where does the result live while the caller waits?

**Dependencies:**
- Thread-safe background executor on the client side
- Could share the same `colab exec` pipeline but with async wrappers

---

### 3. `fn.map()` — Parallel Execution over Inputs

**Problem:** Users want to run the same function over many inputs without a loop.

**API Sketch:**

```python
inputs = [{"epochs": i} for i in range(1, 6)]

# Sequential within the same VM
results = train.map(inputs)

# Or with concurrency hint
results = train.map(inputs, concurrency=2)
```

**Challenges:**
- Colab CLI doesn't support native parallel execution — `.map()` would be sequential within one `colab exec` or require multiple sessions
- True parallelism would require Python threading on the VM (limited by GIL)
- Error isolation — one failing input shouldn't crash the entire map

**Dependencies:**
- May need `@app.cls()` first (stateful runner that accepts jobs)
- Or could be implemented as a simple sequential loop with result aggregation

---

### 4. Volumes — Persistent Storage

**Problem:** Session VM storage is ephemeral — files disappear when the session ends. Users want data to persist across sessions.

**API Sketch:**

```python
# Mount Google Drive as persistent storage
app.volume(name="models", mount="/content/drive/MyDrive/models")

# Or create a named volume
vol = app.volume(name="training-data")
vol.upload("./data.zip", "/volumes/training-data/data.zip")

@app.function(volumes=["models"])
def train():
    # /content/drive/MyDrive/models/model.pt survives session restarts
    ...
```

**Challenges:**
- Google Drive mount requires OAuth scopes beyond basic Colab auth
- Drive has quota and rate limits — not designed for heavy I/O
- Mount takes time (5-15s) and can fail transiently
- Alternative: use `google-colab-cli`'s `colab download`/`colab upload` for explicit file transfer instead of mounted volumes

**Dependencies:**
- Google Drive API OAuth scope
- `google-colab-cli` may need support for Drive mount commands

---

## Tier 2 — Medium Priority

High value, but more complex or less clearly defined.

---

### 5. `@app.web()` — HTTP Endpoints

**Problem:** Users want to expose an HTTP endpoint from the Colab VM — serving Gradio/Streamlit dashboards, REST APIs, or model inference servers.

**API Sketch:**

```python
@app.web(port=8080)
def api(request):
    from fastapi import FastAPI
    app = FastAPI()

    @app.get("/predict")
    async def predict(x: float):
        return {"result": model(x)}

    return app
```

**Challenges:**
- Colab VMs don't have public IPs — needs a tunnel (ngrok, Cloudflare, or `colab` built-in web flag)
- `google-colab-cli` has a `colab web` preview command, but it's for static notebook preview, not arbitrary ports
- Lifetime — the tunnel dies when the function completes; needs a persistent daemon
- Port management — multiple `@app.web()` functions need different ports

**Dependencies:**
- Tunnel service (ngrok, Cloudflare Tunnel) or Colab's built-in `--web` flag
- Persistent session (already have this)

---

### 6. Named Secrets / Secret Management

**Problem:** `app.secret("KEY", "val")` requires hardcoding the value. Users want to store secrets once and reference them by name, like Modal's `modal.Secret.from_name()`.

**API Sketch:**

```python
# CLI-first secret creation
# $ colab secret create HF_TOKEN

# Usage in code
app = App()
app.secret("HF_TOKEN")  # Reads from local secret store

@app.function(secrets=["HF_TOKEN"])
def train():
    token = os.environ["HF_TOKEN"]
```

**Challenges:**
- Needs a local secrets store (encrypted file or keychain)
- Secrets are local to the machine — not shared across team members
- Could leverage `google-colab-cli`'s auth for encrypted storage

**Dependencies:**
- `app.secret(name, value)` inline version (this is already in MVP)
- Local secrets store specification

---

### 7. Multiple Sessions

**Problem:** A user wants to run GPU workloads on different GPU types simultaneously — train on T4, evaluate on CPU.

**API Sketch:**

```python
train_app = App(gpu="T4", session_name="train-session")
eval_app = App(gpu=None, session_name="eval-session")

result_a = train.remote()
result_b = evaluate.remote()
```

**Challenges:**
- Google Colab quota — free tier limits to one GPU runtime
- Colab Pro allows multiple runtimes but with lower quotas
- Cost — multiple sessions consume quota faster

**Dependencies:**
- Session name management (already partially supported)
- Colab Pro / Colab Enterprise for multiple concurrent VMs

---

### 8. Background Jobs / Scheduling

**Problem:** Users want to schedule functions to run on a timer or after a delay.

**API Sketch:**

```python
@app.function
def daily_training():
    ...

# Schedule
job = app.schedule(daily_training, cron="0 6 * * *")  # Daily at 6 AM
job.cancel()
```

**Challenges:**
- Client process must stay alive to trigger scheduled jobs (or use a cron on the VM)
- Colab session has an idle timeout — scheduled jobs would need keep-alive
- `google-colab-cli` doesn't support cron-like scheduling

**Dependencies:**
- Persistent session (already have)
- Keep-alive on the VM side

---

### 9. Progress Callbacks

**Problem:** Users want custom callbacks for `__LAZY_PROGRESS__` markers instead of manual stdout parsing.

**API Sketch:**

```python
def on_progress(value):
    progress_bar.update(value)

result = train.remote(progress_callback=on_progress)
```

**Challenges:**
- Callback runs on the client side, needs a thread to process stdout
- Same thread as `execute()` generator iteration — minor refactoring needed

**Dependencies:**
- stdout protocol's `__LAZY_PROGRESS__` marker (already defined)

---

## Tier 3 — Future Exploration

Ideas worth discussing but not yet well-defined.

| Feature | Description |
|---|---|
| **Cache visualization** | CLI command to show cached artifacts, requirements, and sessions |
| **Colab Pro+ integration** | Higher GPU quotas, priority access, background execution |
| **Model registry** | Track trained models, metadata, and versions across sessions |
| **Artifact browser** | Browse files and artifacts on the active VM |
| **Function chaining / DAG** | `fn1.then(fn2).then(fn3)` — build pipelines |
| **Environment setup scripts** | Custom setup beyond pip — apt, git clone, custom shell scripts |
| **Session snapshots** | Save and restore VM state (notebook checkpointing) |
| **Collaborative sessions** | Share a session with team members |
