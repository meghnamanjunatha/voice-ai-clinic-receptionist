# voice-ai-clinic-receptionist
Voice AI receptionist for booking, rescheduling, and cancelling clinic appointments using Retell AI, FastAPI, SQLite, and OpenAI.

## Production retry safety

Retell may retry failed custom-function requests. Before production deployment, protect write operations with idempotency keys or persisted operation records so a retry cannot create duplicate changes.
