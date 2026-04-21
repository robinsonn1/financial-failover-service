import os
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from twilio.rest import Client
from urllib.parse import urlencode

# 1. SETUP & CONFIGURATION
load_dotenv()
app = FastAPI()

# Global list to store logs for the frontend
logs = []

# Initialize Jinja2 for the HTML dashboard
templates = Jinja2Templates(directory="templates")

# Load environment variables
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
NGROK_URL = os.getenv("NGROK_URL")

# Initialize Twilio Client
if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_NUMBER, NGROK_URL]):
    print("CRITICAL: Missing environment variables in .env file")
else:
    client = Client(TWILIO_SID, TWILIO_TOKEN)

# 2. FRONTEND ROUTES
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Renders the Failover Monitoring Dashboard."""
    return templates.TemplateResponse(request, "index.html")

@app.get("/api/logs")
async def get_logs():
    """Endpoint for the frontend to poll for new log events."""
    return logs

# 3. CORE LOGIC: TRIGGER VOICE ALERT
@app.post("/trigger/{tenant_id}")
async def trigger_voice_alert(tenant_id: str, to_number: str, message: str):
    """Initiates a Voice Call with metadata for failover tracking."""
    try:
        params = {
            "tenant": tenant_id,
            "to_sms": to_number,
            "msg": message
        }
        query_string = urlencode(params)
        full_callback_url = f"{NGROK_URL}/status-callback?{query_string}"

        # Initial Log Entry
        logs.insert(0, {
            "event": "Voice Call Initiated",
            "details": f"Tenant: {tenant_id} | To: {to_number}",
            "status": "pending",
            "raw": {"info": "API Request Sent to Twilio", "to": to_number, "tenant": tenant_id},
            "message_body": message,
            "flag": "🚀 INITIATED"
        })

        call = client.calls.create(
            to=to_number,
            from_=TWILIO_NUMBER,
            twiml=f'<Response><Say>{message}</Say></Response>',
            status_callback=full_callback_url,
            status_callback_event=['completed'],
            timeout=20 
        )
        
        return {"tenant": tenant_id, "call_sid": call.sid, "status": "queued"}
    
    except Exception as e:
        logs.insert(0, {"event": "Error", "details": str(e), "status": "failed", "flag": "❌ ERROR"})
        raise HTTPException(status_code=500, detail=str(e))

# 4. WEBHOOK HANDLER: STATUS CALLBACK & FAILOVER
@app.post("/status-callback")
async def status_callback(
    request: Request, # Crucial for capturing raw payload
    tenant: str, 
    to_sms: str, 
    msg: str, 
    CallStatus: str = Form(...),
    CallDuration: str = Form(None)
):
    """
    Handles the outcome of the call and captures raw Twilio JSON.
    """
    # Capture raw form data for the Payload Inspector
    form_data = await request.form()
    raw_payload = {k: v for k, v in form_data.items()}

    print(f"Webhook Received: {tenant} | Status: {CallStatus} | Duration: {CallDuration}s")
    
    fail_statuses = ['failed', 'busy', 'no-answer', 'canceled']
    is_short_call = False
    
    if CallStatus == 'completed' and CallDuration:
        if int(CallDuration) < 5:
            is_short_call = True

    # Build the Log Entry for this webhook
    log_entry = {
        "event": "Twilio Webhook Received",
        "status": f"Call {CallStatus} ({CallDuration or 0}s)",
        "tenant": tenant,
        "raw": raw_payload,
        "message_body": msg,
        "to": to_sms
    }

    if CallStatus in fail_statuses or is_short_call:
        reason = "Short Call/Hangup" if is_short_call else CallStatus
        log_entry["flag"] = "⚠️ FAILOVER"
        logs.insert(0, log_entry)

        # Trigger SMS Fallback
        sms = client.messages.create(
            body=f"URGENT ALERT for {tenant}: {msg}",
            from_=TWILIO_NUMBER,
            to=to_sms
        )
        
        logs.insert(0, {
            "event": "SMS Fallback Sent",
            "details": f"SID: {sms.sid}",
            "status": "completed",
            "raw": {"sms_sid": sms.sid, "to": to_sms, "body": msg},
            "flag": "📱 SMS SENT"
        })
        return {"event": "failover_triggered", "sms_sid": sms.sid}
    
    # Successful Voice Interaction
    log_entry["flag"] = "✅ SUCCESS"
    logs.insert(0, log_entry)
    return {"event": "call_completed_successfully"}

# 5. SERVER RUNNER
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)