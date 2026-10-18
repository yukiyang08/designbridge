@echo off
REM Start DesignBridge (FastAPI backend + Vue frontend)
echo Starting DesignBridge API...
REM 不能寫 */artifacts/*：uvicorn 的 CLI（click）在 Windows 會把萬用字元展開成實際路徑，
REM 一旦有符合的資料夾（例如 test\artifacts\test_masks）就會變成多餘參數而啟動失敗。
start cmd /k "python -m uvicorn api:app --reload --reload-exclude artifacts"

echo Starting DesignBridge Frontend...
start cmd /k "cd frontend && npm run dev"
