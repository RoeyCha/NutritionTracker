# Nutrition Tracker

MVP web app for logging meals and workouts and viewing your daily calorie balance.

**Stack:** FastAPI, SQLite (SQLAlchemy), HTML + vanilla JavaScript

**Repository:** [https://github.com/RoeyCha/NutritionTracker](https://github.com/RoeyCha/NutritionTracker)

## Features

- Log meals (food name + calories)
- Log workouts (activity type + calories burned)
- View daily summary: consumed vs. burned vs. net calories
- Browse meals and workouts for any selected date

## Project structure

```
NutritionTracker/
├── main.py              # FastAPI app and API routes
├── models.py            # SQLAlchemy models (User, Meal, Workout)
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

```powershell
uvicorn main:app --reload
```

### 5. Open the app

- **Web UI:** [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **API docs:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

Stop the server with `Ctrl+C`.

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Frontend page |
| GET | `/api/summary?date=YYYY-MM-DD` | Daily calorie summary |
| POST | `/api/meals` | Add a meal |
| POST | `/api/workouts` | Add a workout |

### Example: add a meal

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/meals" -Method POST -ContentType "application/json" -Body '{"food_name":"Oatmeal","calories":350}'
```

### Example: add a workout

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/workouts" -Method POST -ContentType "application/json" -Body '{"activity_type":"Running","calories_burned":250}'
```

## Reset local data

Delete the SQLite file and restart the app:

```powershell
Remove-Item nutrition_tracker.db
uvicorn main:app --reload
```

## Updating from GitHub

If you already cloned the repo and want the latest changes:

```powershell
git pull
pip install -r requirements.txt
```
