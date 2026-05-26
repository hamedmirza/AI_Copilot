from fastapi import FastAPI

app = FastAPI(title="{{PROJECT_NAME}}")


@app.get("/health")
def health():
    return {"status": "ok"}
