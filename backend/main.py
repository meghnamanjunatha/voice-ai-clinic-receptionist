from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Voice AI Clinic Receptionist API is running!"}