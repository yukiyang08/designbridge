@echo off
REM Start DesignBridge (FastAPI backend + Vue frontend)
echo Starting DesignBridge API...
start cmd /k "python -m uvicorn api:app --reload --reload-exclude */artifacts/*"

echo Starting DesignBridge Frontend...
start cmd /k "cd frontend && npm run dev"
