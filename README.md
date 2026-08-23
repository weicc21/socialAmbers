# SocialAmbers

A minimal Python application with a Streamlit frontend and Flask backend.

## Run locally

Requires Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start the backend in one terminal:

```bash
source .venv/bin/activate
flask --app backend.app run --debug --port 5000
```

Start the frontend in another terminal:

```bash
source .venv/bin/activate
streamlit run frontend/app.py
```

Open http://localhost:8501. The frontend uses `http://localhost:5000` by
default; set `API_URL` to point it at a different backend.

## API

- `GET /api/health` checks backend availability.
- `GET /api/messages` lists messages newest first.
- `POST /api/messages` accepts JSON shaped as `{"text": "..."}`.

Messages are intentionally stored in memory for this bootstrap and reset when
the Flask process restarts.
