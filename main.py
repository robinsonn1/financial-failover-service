import os
import uvicorn
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from twilio.rest import Client
from urllib.parse import urlencode
from hubspot import HubSpot
from hubspot.crm.contacts import PublicObjectSearchRequest, SimplePublicObjectInputForCreate

# --- SETUP & CONFIGURATION ---
load_dotenv()
app = FastAPI()
logs = []
templates = Jinja2Templates(directory="templates")

# Initialize Twilio & HubSpot
client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
hs_client = HubSpot(access_token=os.getenv("HUBSPOT_ACCESS_TOKEN"))

TWILIO_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID")
NGROK_URL = os.getenv("NGROK_URL")

# --- DASHBOARD ROUTES ---
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.get("/api/logs")
async def get_logs():
    return logs

# --- CRM LOGIC: ADD CONTACT (FIXED FOR LATEST SDK) ---
@app.post("/api/add-contact")
async def add_hubspot_contact(phone: str = Form(...), first_name: str = Form(...)):
    try:
        # Fixed: Use SimplePublicObjectInputForCreate and the specific parameter name
        properties = {"phone": phone, "firstname": first_name, "lastname": "Demo User"}
        contact_input = SimplePublicObjectInputForCreate(properties=properties)
        
        # Fixed: The positional argument name is simple_public_object_input_for_create
        hs_client.crm.contacts.basic_api.create(
            simple_public_object_input_for_create=contact_input
        )
        
        logs.insert(0, {
            "event": "HubSpot Sync", 
            "details": f"Added {first_name} to CRM", 
            "flag": "🧡 CRM_ADD",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        return {"status": "success"}
    except Exception as e:
        logs.insert(0, {"event": "HubSpot Error", "details": str(e), "flag": "❌ CRM_ERR"})
        raise HTTPException(status_code=500, detail=str(e))

# --- STEP 1: TRIGGER VOICE ALERT ---
@app.post("/trigger/{tenant_id}")
async def trigger_voice_alert(tenant_id: str, to_number: str, message: str):
    try:
        params = {"tenant": tenant_id, "to_sms": to_number, "msg": message}
        query_string = urlencode(params)
        full_callback_url = f"{NGROK_URL}/status-callback?{query_string}"

        logs.insert(0, {
            "event": "Voice Workflow Start",
            "details": f"Initiating call to {to_number}",
            "status": "pending",
            "flag": "🚀 CALL_START",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "raw": {"tenant": tenant_id, "message": message}
        })

        call = client.calls.create(
            to=to_number,
            from_=TWILIO_NUMBER,
            twiml=f'<Response><Say>{message}</Say></Response>',
            status_callback=full_callback_url,
            status_callback_event=['completed'],
            timeout=20 
        )
        return {"status": "initiated", "call_sid": call.sid}
    except Exception as e:
        logs.insert(0, {"event": "System Error", "details": str(e), "flag": "❌ ERROR"})
        raise HTTPException(status_code=500, detail=str(e))

# --- STEP 2: STATUS CALLBACK & RCS/SMS FAILOVER ---
@app.post("/status-callback")
async def status_callback(
    request: Request,
    tenant: str, 
    to_sms: str, 
    msg: str, 
    CallStatus: str = Form(...),
    CallDuration: str = Form(None)
):
    form_data = await request.form()
    raw_payload = {k: v for k, v in form_data.items()}
    
    fail_statuses = ['failed', 'busy', 'no-answer', 'canceled']
    is_short_call = (CallStatus == 'completed' and CallDuration and int(CallDuration) < 5)

    if CallStatus in fail_statuses or is_short_call:
        contact = None
        try:
            search_request = PublicObjectSearchRequest(
                filter_groups=[{"filters": [{"propertyName": "phone", "operator": "EQ", "value": to_sms}]}],
                properties=["firstname"]
            )
            results = hs_client.crm.contacts.search_api.do_search(public_object_search_request=search_request)
            contact = results.results[0] if results.results else None
        except Exception as e:
            print(f"HS Search Error: {e}")

        first_name = contact.properties['firstname'] if contact else "Member"
        personalized_msg = f"Hi {first_name}, {msg}"

        logs.insert(0, {
            "event": "CRM Data Fetched",
            "details": f"Personalizing for {first_name}",
            "flag": "🧡 HUBSPOT",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "raw": contact.to_dict() if contact else {"match": "false"}
        })

        # Orchestrated Dispatch
        message_res = client.messages.create(
            body=personalized_msg,
            messaging_service_sid=MESSAGING_SERVICE_SID,
            to=to_sms
        )
        
        logs.insert(0, {
            "event": "Message Delivered",
            "details": f"Channel: RCS/SMS | SID: {message_res.sid}",
            "status": "completed",
            "flag": "📱 SENT",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "raw": {"sid": message_res.sid, "body": personalized_msg}
        })
    else:
        logs.insert(0, {
            "event": "Voice Call Success",
            "details": f"Member acknowledged via Voice.",
            "status": "completed",
            "flag": "✅ SUCCESS",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "raw": raw_payload
        })

    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)