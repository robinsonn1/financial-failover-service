import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, HTTPException
from twilio.rest import Client
from urllib.parse import urlencode
import uvicorn


# Load variables from .env
load_dotenv()

app = FastAPI()

# Initialize Twilio Client
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
NGROK_URL = os.getenv("NGROK_URL")

if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_NUMBER, NGROK_URL]):
    raise ValueError("Missing environment variables in .env file")

client = Client(TWILIO_SID, TWILIO_TOKEN)

@app.get("/")
def health_check():
    return {"status": "online", "multi_tenant": True}

@app.post("/trigger/{tenant_id}")
async def trigger_voice_alert(tenant_id: str, to_number: str, message: str):
    try:
        # 1. Create a dictionary of your parameters
        params = {
            "tenant": tenant_id,
            "to_sms": to_number,
            "msg": message
        }
        
        # 2. Use urlencode to handle spaces and special characters safely
        # This turns "Fraud Alert" into "Fraud+Alert"
        query_string = urlencode(params)
        
        full_callback_url = f"{NGROK_URL}/status-callback?{query_string}"
        print(f"Submitting Callback URL: {full_callback_url}")

        call = client.calls.create(
            to=to_number,
            from_=TWILIO_NUMBER,
            twiml=f'<Response><Say>{message}</Say></Response>',
            status_callback=full_callback_url,
            status_callback_event=['completed']
        )
        return {"tenant": tenant_id, "call_sid": call.sid, "status": "queued"}
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/status-callback")
async def status_callback(
    tenant: str, 
    to_sms: str, 
    msg: str, 
    CallStatus: str = Form(...),
    CallDuration: str = Form(None) # Twilio sends this in seconds
):
    # 1. Handle explicit failures
    fail_statuses = ['failed', 'busy', 'no-answer', 'canceled']
    
    # 2. Handle "Short Calls" (User hung up within 5 seconds)
    is_short_call = False
    if CallStatus == 'completed' and CallDuration:
        if int(CallDuration) < 5:
            is_short_call = True
            print(f"Detected short call ({CallDuration}s). Triggering fallback.")

    if CallStatus in fail_statuses or is_short_call:
        sms = client.messages.create(
            body=f"URGENT: {msg}. (We tried calling but couldn't reach you).",
            from_=TWILIO_NUMBER,
            to=to_sms
        )
        return {"event": "failover_triggered", "reason": CallStatus if not is_short_call else "short_call"}
    
    return {"event": "user_notified_successfully"}
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)