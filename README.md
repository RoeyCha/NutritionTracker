# Nutrition Tracker

MVP web app for logging meals and workouts and viewing your daily calorie balance.

**Stack:** FastAPI, SQLite (SQLAlchemy), HTML + vanilla JavaScript

**Repository:** [https://github.com/RoeyCha/NutritionTracker](https://github.com/RoeyCha/NutritionTracker)

## Features

- Log meals (food name + calories)
- Log workouts (activity type + calories burned)
- View daily summary: consumed vs. burned vs. net calories
- Browse meals and workouts for any selected date
- **English and Hebrew UI** with RTL layout for Hebrew
- Full UTF-8 support for Hebrew meal and workout names
- **User accounts** with login, registration, and profile management
- Each user has isolated meals, workouts, and daily summaries
- **AI calorie estimation** for meals and workouts (Google Gemini, with local fallback)

## AI features (Google Gemini)

One API key powers calorie estimates and daily insights.

1. Copy `.env.example` to `.env`
2. Add your Gemini API key:

```env
GEMINI_API_KEY=your-gemini-api-key-here
GEMINI_MODEL=gemini-2.5-flash
```

3. Restart with `.\start.ps1`

When you add or edit a meal/workout, calories are estimated automatically and shown in a popup. Without an API key, the app uses local fallback estimates so you can still test the flow.

The **Get AI Insight** button sends the selected day's meals and workouts to Gemini and displays encouraging feedback plus a health tip. Insights respect the selected summary date and UI language (English/Hebrew).

## Project structure

```
NutritionTracker/
├── main.py              # FastAPI app and API routes
├── models.py            # SQLAlchemy models (User, Meal, Workout)
├── auth.py              # Password hashing and JWT authentication
├── ai_calories.py       # AI/local calorie estimation
├── gemini_insight.py    # Gemini daily feedback
├── seed.py              # Test user and sample data seeding
├── requirements.txt     # Python dependencies
├── templates/
│   └── index.html       # Frontend UI
└── nutrition_tracker.db # Created automatically on first run (not in git)
```

## Prerequisites

- [Python 3.10+](https://www.python.org/downloads/)
- [Git](https://git-scm.com/downloads)

## Install and run

### 1. Clone the repository

```powershell
git clone https://github.com/RoeyCha/NutritionTracker.git
cd NutritionTracker
```

### 2. Create and activate a virtual environment

**Windows (PowerShell):**

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If activation is blocked, run once:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**macOS / Linux:**

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Start the server

Always use the start script — it stops old runs and starts one fresh server on port 8000 (with auto-reload on code changes):

```powershell
.\start.ps1
```

Do **not** run multiple `uvicorn` terminals; leftover processes cause "Not Found" and stale-server errors.

### 5. Open the app

- **Web UI:** [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **API docs:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

Stop the server with `Ctrl+C`.

## Test account

On first startup, the app creates a demo user with sample data:

| Field | Value |
|-------|-------|
| Username | `test` |
| Password | `1234` |

Sample data includes meals and workouts for today and yesterday.

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Frontend page |
| POST | `/api/auth/register` | Create account |
| POST | `/api/auth/login` | Sign in |
| GET | `/api/auth/me` | Current user profile (auth required) |
| PUT | `/api/profile` | Update profile (auth required) |
| POST | `/api/ai-insight` | Gemini daily feedback and health tip (auth required) |
| GET | `/api/summary?date=YYYY-MM-DD` | Daily calorie summary (auth required) |
| POST | `/api/meals` | Add a meal (auth required) |
| POST | `/api/workouts` | Add a workout (auth required) |

Protected routes require a Bearer token from login/register:

```powershell
$login = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/auth/login" -Method POST -ContentType "application/json" -Body '{"username":"test","password":"1234"}'
$headers = @{ Authorization = "Bearer $($login.access_token)" }
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/summary" -Headers $headers
```

### Example: add a meal

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/meals" -Method POST -Headers $headers -ContentType "application/json" -Body '{"food_name":"Oatmeal","calories":350}'
```

### Example: add a workout

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/workouts" -Method POST -Headers $headers -ContentType "application/json" -Body '{"activity_type":"Running","calories_burned":250}'
```

## Reset local data

Delete the SQLite file and restart the app (stop the server first if it is running):

```powershell
Remove-Item nutrition_tracker.db
uvicorn main:app --reload
```

The test user and sample data are recreated automatically on startup.

## Updating from GitHub

If you already cloned the repo and want the latest changes:

```powershell
git pull
pip install -r requirements.txt
```
