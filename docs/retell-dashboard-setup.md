# Retell Dashboard Custom-Function Setup

Use this document when entering the six custom functions in Retell. Replace `<RENDER_SERVICE_URL>` with the Render hostname only, for example `voice-ai-clinic-receptionist.onrender.com`. Do not leave the angle brackets in the saved URL.

Do not add `CLINIKO_API_KEY` or `RETELL_API_KEY` to any Retell header, parameter, dynamic variable, or prompt. Retell sends `X-Retell-Signature` automatically. The FastAPI `/retell/*` adapter routes verify it using the server-side `RETELL_API_KEY` stored on Render.

Use a 15-second timeout for every function. The backend's default Cliniko timeout is 10 seconds, leaving time for FastAPI to translate an upstream result before Retell stops waiting.

## 1. `find_or_create_patient`

1. **Function name**

   `find_or_create_patient`

2. **Description**

   Find a Cliniko patient by normalized phone number, or create the patient when no match exists. This can write data, so confirm the caller's full name and phone number before calling. If multiple patients share the phone number, stop and escalate instead of guessing.

3. **HTTP method**

   `POST`

4. **Complete endpoint**

   `https://<RENDER_SERVICE_URL>/patients`

5. **Timeout in milliseconds**

   `15000`

6. **Headers**

   Add no custom headers. Retell supplies `Content-Type: application/json` and `X-Retell-Signature`. Do not add either API key.

7. **Query parameters**

   None. `full_name` and `phone` are request-body arguments, not query parameters.

8. **Payload: args only**

   Enabled. FastAPI expects the argument object as the complete JSON body, without Retell's `name`, `call`, or `args` wrapper.

9. **Request-body JSON schema**

   ```json
   {
     "type": "object",
     "additionalProperties": false,
     "properties": {
       "full_name": {
         "type": "string",
         "minLength": 1,
         "maxLength": 511,
         "description": "The caller's confirmed full name."
       },
       "phone": {
         "type": "string",
         "minLength": 1,
         "maxLength": 50,
         "description": "The caller's confirmed phone number, including country code when known."
       }
     },
     "required": ["full_name", "phone"]
   }
   ```

10. **Stored Retell dynamic variables**

    | Variable | JSON path |
    | --- | --- |
    | `patient_id` | `id` |
    | `patient_full_name` | `full_name` |
    | `patient_phone` | `phone` |
    | `is_new_patient` | `is_new_patient` |

11. **Talk While Waiting**

    Enabled. Suggested prompt/static phrase: “One moment while I check your patient record.”

12. **Talk After Action Completed**

    Enabled, so the agent can continue the workflow using the patient result or explain a conflict.

13. **Test request**

    Use a dedicated Cliniko test patient because this operation may create a record.

    ```json
    {
      "full_name": "Asha Rao",
      "phone": "+61 412 345 678"
    }
    ```

14. **Expected successful response**

    ```json
    {
      "id": "123456789",
      "full_name": "Asha Rao",
      "phone": "61412345678",
      "is_new_patient": false
    }
    ```

15. **Dependencies on earlier tool results**

    None. It depends on caller-confirmed `full_name` and `phone`. Its stored `patient_id` is required by `list_patient_appointments` and `book_appointment`.

16. **Common configuration mistakes**

    - Leaving Payload: args only disabled.
    - Putting `full_name` or `phone` in query parameters.
    - Calling before confirming the spelling and phone number even though the tool may create a patient.
    - Adding Cliniko or Retell API keys as headers.
    - Testing repeatedly with new phone numbers and unintentionally creating patients.

## 2. `list_patient_appointments`

1. **Function name**

   `list_patient_appointments`

2. **Description**

   List a known Cliniko patient's non-cancelled appointments in chronological order. By default, return only upcoming appointments. Use the `patient_id` returned by `find_or_create_patient`; never ask the caller for an internal ID.

3. **HTTP method**

   `GET`

4. **Complete endpoint**

   `https://<RENDER_SERVICE_URL>/patients/{{patient_id}}/appointments`

   `patient_id` is a path dynamic variable. It is not a query parameter or request-body argument.

5. **Timeout in milliseconds**

   `15000`

6. **Headers**

   Add no custom headers. Retell supplies `X-Retell-Signature`; this public backend route does not require a manually configured credential header.

7. **Query parameters**

   | Name | Value type | Requirement | Source |
   | --- | --- | --- | --- |
   | `include_past` | Boolean | Optional | Constant `false` |

   Configure `include_past` using Retell's constant-value mode, not the LLM-provided description mode.

8. **Payload: args only**

   Disabled/not applicable. A GET request has no JSON body.

9. **Request-body JSON schema**

   Not applicable. Do not configure a parameter schema or request body for this GET tool. `patient_id` belongs in the endpoint path and `include_past` belongs in the query string.

10. **Stored Retell dynamic variables**

    None. The response is an array and the intended appointment might not be element zero. Do not store paths such as `[0].appointment_id` as the selected appointment. Let the agent present the returned choices and pass the caller-selected appointment's fields as later tool arguments.

11. **Talk While Waiting**

    Enabled. Suggested prompt/static phrase: “One moment while I look up your upcoming appointments.”

12. **Talk After Action Completed**

    Enabled, so the agent reads the single appointment or asks the caller to choose when multiple appointments are returned.

13. **Test request**

    Set the test dynamic variable `patient_id` to a real test patient's ID, for example `123456789`. Retell should call:

    ```text
    GET https://<RENDER_SERVICE_URL>/patients/123456789/appointments?include_past=false
    ```

    There is no request body.

14. **Expected successful response**

    ```json
    [
      {
        "appointment_id": "987654321",
        "patient_id": "123456789",
        "practitioner_id": "2001",
        "business_id": "1001",
        "appointment_type_id": "3001",
        "starts_at": "2026-07-21T09:30:00+10:00",
        "status": "booked"
      }
    ]
    ```

    An empty array is also a successful response when no upcoming appointments exist.

15. **Dependencies on earlier tool results**

    Requires `patient_id`, stored from JSON path `id` after `find_or_create_patient`. The selected appointment supplies `appointment_id`, `business_id`, `practitioner_id`, and `appointment_type_id` to later rescheduling or cancellation steps.

16. **Common configuration mistakes**

    - Treating `patient_id` as a query parameter instead of a path dynamic variable.
    - Leaving `{{patient_id}}` unresolved during testing.
    - Making `include_past` LLM-provided instead of constant `false`.
    - Configuring a request body for a GET tool.
    - Automatically choosing the first array item when multiple appointments exist.
    - Reading internal IDs aloud to the caller.

## 3. `search_availability`

1. **Function name**

   `search_availability`

2. **Description**

   Search Cliniko for available appointment start times. Searches are read-only, dates use `YYYY-MM-DD`, and the inclusive search window must not exceed seven days.

3. **HTTP method**

   `GET`

4. **Complete endpoint**

   `https://<RENDER_SERVICE_URL>/availability`

5. **Timeout in milliseconds**

   `15000`

6. **Headers**

   Add no custom headers. Retell supplies `X-Retell-Signature`; do not expose either API key.

7. **Query parameters**

   | Name | Value type | Requirement | Source |
   | --- | --- | --- | --- |
   | `business_name` | String | Required | LLM-provided from trusted configured context or the caller's clinic choice |
   | `practitioner_name` | String | Required | LLM-provided from the caller's practitioner or specialty choice |
   | `appointment_type_name` | String | Required | LLM-provided from trusted configured context or the caller's service choice |
   | `from_date` | String in `YYYY-MM-DD` format | Required | LLM-provided from the caller's date preference |
   | `to_date` | String in `YYYY-MM-DD` format | Required | LLM-provided from the caller's date preference |

   Configure all five in Retell's parameter-description/LLM-provided mode. They are query parameters, not JSON-body arguments.

8. **Payload: args only**

   Disabled/not applicable. A GET request has no JSON body.

9. **Request-body JSON schema**

   Not applicable. Do not configure a parameter schema or body for this GET tool. Configure the five values in the dashboard's query-parameter section.

10. **Stored Retell dynamic variables**

    None. The response is an array of slots, and the caller may choose any returned entry. Do not store `[0].start_time` as the selected time. Pass the chosen entry's `start_time` and IDs into the booking or rescheduling body.

11. **Talk While Waiting**

    Enabled. Suggested prompt/static phrase: “One moment while I check the available times.”

12. **Talk After Action Completed**

    Enabled, so the agent offers two or three returned slots or explains that none were found.

13. **Test request**

    Use human-readable names from the caller and future dates no more than seven days apart. For a single-day search, use the same date for `from_date` and `to_date`:

    ```text
    GET https://<RENDER_SERVICE_URL>/availability?business_name=Whitefield&practitioner_name=Dermatologist&appointment_type_name=Initial%20Dermatology&from_date=2026-07-20&to_date=2026-07-20
    ```

    There is no request body.

14. **Expected successful response**

    ```json
    [
      {
        "start_time": "2026-07-21T09:30:00+10:00",
        "business_id": "1001",
        "practitioner_id": "2001",
        "appointment_type_id": "3001"
      }
    ]
    ```

    An empty array is also a successful response when no matching slots exist.

15. **Dependencies on earlier tool results**

    The three names come from trusted clinic configuration or the caller's stated preferences. For booking, pass the IDs from the caller-selected availability response to `book_appointment`; for rescheduling, the existing appointment identifies the clinic, practitioner, and appointment type whose display names should be used. Dates come from the caller's preference.

16. **Common configuration mistakes**

    - Putting the five values in a JSON body instead of query parameters.
    - Sending natural-language dates instead of `YYYY-MM-DD`.
    - Searching a range longer than seven days.
    - Supplying Cliniko IDs instead of display names.
    - Treating a timezone-aware `start_time` response as a date-only value.
    - Assuming an empty array is an error.

## 4. `book_appointment`

1. **Function name**

   `book_appointment`

2. **Description**

   Create one Cliniko appointment after the caller explicitly confirms the patient, clinic, practitioner, appointment type, and timezone-aware start time. Call once only; do not automatically retry a failed creation.

3. **HTTP method**

   `POST`

4. **Complete endpoint**

   `https://<RENDER_SERVICE_URL>/appointments`

5. **Timeout in milliseconds**

   `15000`

6. **Headers**

   Add no custom headers. Retell supplies `Content-Type: application/json` and `X-Retell-Signature`. Never add either API key.

7. **Query parameters**

   None. All five inputs are request-body arguments.

8. **Payload: args only**

   Enabled. FastAPI expects the flat argument object.

9. **Request-body JSON schema**

   ```json
   {
     "type": "object",
     "additionalProperties": false,
     "properties": {
       "patient_id": {
         "type": "string",
         "pattern": "^[1-9]\\d*$",
         "description": "Cliniko patient ID returned by find_or_create_patient."
       },
       "business_id": {
         "type": "string",
         "pattern": "^[1-9]\\d*$",
         "description": "Confirmed Cliniko business ID."
       },
       "practitioner_id": {
         "type": "string",
         "pattern": "^[1-9]\\d*$",
         "description": "Confirmed Cliniko practitioner ID."
       },
       "appointment_type_id": {
         "type": "string",
         "pattern": "^[1-9]\\d*$",
         "description": "Confirmed Cliniko appointment type ID."
       },
       "starts_at": {
         "type": "string",
         "format": "date-time",
         "description": "Confirmed available start time as timezone-aware ISO 8601."
       }
     },
     "required": [
       "patient_id",
       "business_id",
       "practitioner_id",
       "appointment_type_id",
       "starts_at"
     ]
   }
   ```

10. **Stored Retell dynamic variables**

    | Variable | JSON path |
    | --- | --- |
    | `booked_appointment_id` | `appointment_id` |
    | `booked_starts_at` | `starts_at` |
    | `booked_appointment_status` | `status` |

11. **Talk While Waiting**

    Enabled. Suggested prompt/static phrase: “One moment while I book that appointment.”

12. **Talk After Action Completed**

    Enabled, so the agent confirms the booking only after a successful response or handles a no-longer-available slot.

13. **Test request**

    This creates a real Cliniko appointment. Use a dedicated test patient and a currently available slot returned by `search_availability`.

    ```json
    {
      "patient_id": "123456789",
      "business_id": "1001",
      "practitioner_id": "2001",
      "appointment_type_id": "3001",
      "starts_at": "2026-07-21T09:30:00+10:00"
    }
    ```

14. **Expected successful response**

    ```json
    {
      "appointment_id": "987654321",
      "patient_id": "123456789",
      "business_id": "1001",
      "practitioner_id": "2001",
      "appointment_type_id": "3001",
      "starts_at": "2026-07-21T09:30:00+10:00",
      "status": "booked"
    }
    ```

15. **Dependencies on earlier tool results**

    `patient_id` comes from `find_or_create_patient`. The business, practitioner, appointment-type IDs and exact timezone-aware `starts_at` come from the caller-selected `search_availability` result. Explicit caller confirmation is required immediately before calling.

16. **Common configuration mistakes**

    - Leaving Payload: args only disabled.
    - Sending IDs as JSON numbers rather than strings.
    - Removing the timezone offset from `starts_at`.
    - Using a time that was not returned by availability.
    - Calling before explicit confirmation.
    - Automatically retrying after an uncertain failure and risking a duplicate booking.

## 5. `reschedule_appointment`

1. **Function name**

   `reschedule_appointment`

2. **Description**

   Move the Cliniko appointment selected from `list_patient_appointments` after the caller explicitly confirms it and the new timezone-aware start time. Call once only; do not automatically retry.

3. **HTTP method**

   `PATCH`

4. **Complete endpoint**

   `https://<RENDER_SERVICE_URL>/retell/appointments/reschedule`

5. **Timeout in milliseconds**

   `15000`

6. **Headers**

   Add no custom headers. Retell supplies `Content-Type: application/json` and `X-Retell-Signature`. FastAPI verifies the signature using the server-side key on Render. Do not add `RETELL_API_KEY` or `CLINIKO_API_KEY` here.

7. **Query parameters**

   None. `appointment_id` and `starts_at` are normal request-body arguments. There is no appointment ID path variable on this adapter route.

8. **Payload: args only**

   Enabled. Signature verification and FastAPI parsing both expect the flat argument object as the raw JSON body.

9. **Request-body JSON schema**

   ```json
   {
     "type": "object",
     "additionalProperties": false,
     "properties": {
       "appointment_id": {
         "type": "string",
         "pattern": "^[1-9]\\d*$",
         "description": "Trusted internal Cliniko appointment ID selected from list_patient_appointments. Never ask the caller for it."
       },
       "starts_at": {
         "type": "string",
         "format": "date-time",
         "description": "The newly confirmed start time as timezone-aware ISO 8601."
       }
     },
     "required": ["appointment_id", "starts_at"]
   }
   ```

10. **Stored Retell dynamic variables**

    | Variable | JSON path |
    | --- | --- |
    | `rescheduled_appointment_id` | `appointment_id` |
    | `rescheduled_starts_at` | `starts_at` |
    | `rescheduled_appointment_status` | `status` |

11. **Talk While Waiting**

    Enabled. Suggested prompt/static phrase: “One moment while I update that appointment.”

12. **Talk After Action Completed**

    Enabled, so the agent announces the new time only after success or offers another search when the slot is unavailable.

13. **Test request**

    This changes a real Cliniko appointment. Use the appointment created during the booking test and a fresh slot returned by availability.

    ```json
    {
      "appointment_id": "987654321",
      "starts_at": "2026-07-23T14:00:00+10:00"
    }
    ```

14. **Expected successful response**

    ```json
    {
      "appointment_id": "987654321",
      "starts_at": "2026-07-23T14:00:00+10:00",
      "status": "rescheduled"
    }
    ```

15. **Dependencies on earlier tool results**

    `appointment_id` comes from the appointment the caller selected from `list_patient_appointments`. `starts_at` is the caller-selected timezone-aware value from a subsequent `search_availability` result. Explicit confirmation is required immediately before calling.

16. **Common configuration mistakes**

    - Using the old `/appointments/{{appointment_id}}` endpoint instead of the `/retell/appointments/reschedule` adapter.
    - Configuring `appointment_id` as a path or query variable instead of a body argument.
    - Leaving Payload: args only disabled.
    - Manually adding the Retell API key or signature header.
    - Sending a timezone-naive datetime.
    - Retrying automatically after an uncertain response.

## 6. `cancel_appointment`

1. **Function name**

   `cancel_appointment`

2. **Description**

   Cancel the Cliniko appointment selected from `list_patient_appointments` without deleting it, after the caller explicitly confirms the appointment and cancellation. Call once only; do not automatically retry.

3. **HTTP method**

   `POST`

4. **Complete endpoint**

   `https://<RENDER_SERVICE_URL>/retell/appointments/cancel`

5. **Timeout in milliseconds**

   `15000`

6. **Headers**

   Add no custom headers. Retell supplies `Content-Type: application/json` and `X-Retell-Signature`. FastAPI verifies the signature using the server-side key on Render. Do not add `RETELL_API_KEY` or `CLINIKO_API_KEY` here.

7. **Query parameters**

   None. `appointment_id`, `cancellation_reason`, and optional `note` are request-body arguments. There is no appointment ID path variable on this adapter route.

8. **Payload: args only**

   Enabled. Signature verification and FastAPI parsing both expect the flat argument object as the raw JSON body.

9. **Request-body JSON schema**

   ```json
   {
     "type": "object",
     "additionalProperties": false,
     "properties": {
       "appointment_id": {
         "type": "string",
         "pattern": "^[1-9]\\d*$",
         "description": "Trusted internal Cliniko appointment ID selected from list_patient_appointments. Never ask the caller for it."
       },
       "cancellation_reason": {
         "type": "integer",
         "enum": [10, 20, 30, 40, 50, 60],
         "description": "Cliniko reason code: 10 feeling better, 20 condition worse, 30 sick, 40 away, 50 other, 60 work."
       },
       "note": {
         "type": "string",
         "maxLength": 5000,
         "description": "Optional brief note only when the caller provides useful additional context. Do not invent one."
       }
     },
     "required": ["appointment_id", "cancellation_reason"]
   }
   ```

10. **Stored Retell dynamic variables**

    | Variable | JSON path |
    | --- | --- |
    | `cancelled_appointment_id` | `appointment_id` |
    | `cancelled_appointment_status` | `status` |
    | `recorded_cancellation_reason` | `cancellation_reason` |

11. **Talk While Waiting**

    Enabled. Suggested prompt/static phrase: “One moment while I cancel that appointment.”

12. **Talk After Action Completed**

    Enabled, so the agent confirms cancellation only after success or explains that the appointment is missing/already cancelled.

13. **Test request**

    This cancels a real Cliniko appointment. Use the dedicated appointment from the booking/rescheduling tests.

    ```json
    {
      "appointment_id": "987654321",
      "cancellation_reason": 60,
      "note": "Work meeting moved to the same time."
    }
    ```

14. **Expected successful response**

    ```json
    {
      "appointment_id": "987654321",
      "status": "cancelled",
      "cancellation_reason": 60
    }
    ```

15. **Dependencies on earlier tool results**

    `appointment_id` comes from the appointment the caller selected from `list_patient_appointments`. The reason code comes from mapping the caller's stated reason, and `note` is included only if the caller volunteered it. Explicit confirmation is required immediately before calling.

16. **Common configuration mistakes**

    - Using the old `/appointments/{{appointment_id}}/cancel` endpoint instead of the `/retell/appointments/cancel` adapter.
    - Configuring `appointment_id` as a path or query variable instead of a body argument.
    - Sending the reason as text instead of one of the allowed integer codes.
    - Making `note` required or inventing note content.
    - Leaving Payload: args only disabled.
    - Adding either API key to Retell headers.
    - Retrying automatically after an uncertain response.
