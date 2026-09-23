# Trie Code — Real-time Food Redistribution (AppCon 2026)

Donors post surplus food through a Telegram bot. Listings appear live on a map with an expiry countdown. The nearest partner org claims a listing in one tap, unclaimed listings widen their search radius automatically, and pickups are confirmed with a photo.

## Structure
- `backend/`: FastAPI and the Telegram bot
- `frontend/`: React, Vite, Tailwind, Leaflet
- `supabase/`: SQL migrations and seed data
- `scripts/`: dev helpers (apply migrations, simulate posts)

## Local setup
1. Copy `backend/.env.example` to `backend/.env` and `frontend/.env.example` to `frontend/.env`, then fill in the values.
2. Start the backend:
   ```sh
   cd backend
   python -m venv .venv
   .venv/Scripts/activate        # Windows
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```
3. Start the frontend:
   ```sh
   cd frontend
   npm install
   npm run dev
   ```
