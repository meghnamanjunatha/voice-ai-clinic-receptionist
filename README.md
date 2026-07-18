# voice-ai-clinic-receptionist
Voice AI receptionist for booking, rescheduling, and cancelling clinic appointments using Retell AI, FastAPI, SQLite, and OpenAI.

## Production retry safety

Retell may retry failed custom-function requests. Before production deployment, protect write operations with idempotency keys or persisted operation records so a retry cannot create duplicate changes.

## Deploying to Render

The existing `GET /` route is a dependency-free health endpoint. It returns HTTP 200 without calling Cliniko, so use `/` as the Render health-check path.

### Create the web service

1. Push the repository to a Git provider supported by Render.
2. In Render, create a **Web Service** from the repository.
3. Select the Python runtime and the repository root as the root directory.
4. Configure the build command:

   ```sh
   pip install -r requirements.txt
   ```

5. Configure the production start command:

   ```sh
   uvicorn backend.main:app --host 0.0.0.0 --port $PORT
   ```

6. Under **Advanced**, set the health-check path to `/`.

Render provides `PORT`; do not hard-code it. Uvicorn must bind to `0.0.0.0` so Render can route public traffic to the service.

### Configure environment variables

Add these under the Render service's **Environment** settings:

| Name | Required | Description |
| --- | --- | --- |
| `CLINIKO_API_KEY` | Yes | Cliniko API key. Store as a secret. |
| `CLINIKO_SHARD` | Yes* | Cliniko shard from the account URL, for example `au5`. |
| `CLINIKO_USER_AGENT` | Yes | Application name and a contact email. |
| `RETELL_API_KEY` | Yes for Retell routes | Retell API key used to verify `X-Retell-Signature`. |
| `CLINIKO_TIMEOUT_SECONDS` | No | Cliniko request timeout; defaults to `10`. |
| `CLINIKO_API_BASE_URL` | No | Full Cliniko API URL override. If set, it takes precedence over `CLINIKO_SHARD`. |

\* `CLINIKO_SHARD` is not needed when `CLINIKO_API_BASE_URL` is explicitly set.

Do not upload or commit the local `.env` file. Render injects these values into the running service.

### Verify the deployment

After Render reports a successful deployment, open:

```text
https://YOUR-SERVICE.onrender.com/
```

The expected response is:

```json
{"message":"Voice AI Clinic Receptionist API is running!"}
```

Use the service's HTTPS URL as `backend_base_url` when configuring the Retell custom tools.
