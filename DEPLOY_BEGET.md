# Deploy to Beget (Passenger WSGI)

## 1) Upload
- Upload the project contents to your hosting root, e.g. `~/www/your-domain/`.
- Root must contain: `app.py`, `passenger_wsgi.py`, `templates/`, `static/`, and your SQLite DB (`app.db` or the file from SQLITE_DB).

## 2) Enable Python/Passenger
- In Beget panel, enable Python/Passenger for the domain.
- Set the application startup file to `passenger_wsgi.py`.

## 3) Create venv & install deps (SSH)
```bash
cd ~/www/your-domain
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4) Environment
- Create `.env` from `.env.example` and set values:
  - `SECRET_KEY`
  - `DATABASE_URL` (optional) or `SQLITE_DB`
  - `FLASK_ENV=production`
  - `FLASK_DEBUG=0`

## 5) Restart
- Restart the app from Beget panel, or touch `tmp/restart.txt` if supported.

## Notes
- `app.py` reads env vars directly; no extra loader required.
- Local run still works: `python app.py`.
