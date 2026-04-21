# Multi-Tenant Financial Alerting & Failover Service

## Overview
This service provides a high-reliability notification gateway designed for Financial Institutions (Credit Unions). It addresses the critical need for urgent account alerts by implementing a **Voice-First, SMS-Fallback** architecture.

### Key Features
- **Multi-Tenant Architecture:** Designed to support multiple "licensed" organizations using Twilio Subaccounts.
- **Intelligent Failover:** Automatically triggers an SMS alert if a Voice call is busy, fails, goes to voicemail (short duration), or is not answered.
- **Event-Driven:** Uses Twilio StatusCallbacks (Webhooks) to manage call lifecycles asynchronously.
- **Secure:** Environment-based configuration to protect sensitive API credentials.

## Technical Stack
- **Language:** Python 3.12+
- **Framework:** FastAPI (Asynchronous Web Framework)
- **Communications:** Twilio API (Voice & Messaging)
- **Tunneling:** Ngrok (for local webhook testing)

## Project Structure
```text
.
├── main.py              # Core application logic & Webhook handlers
├── .env.example         # Template for environment variables
├── .gitignore           # Ensures sensitive data is not committed
├── requirements.txt     # Project dependencies
└── README.md            # Project documentation
Setup & Installation
Clone the repository:

Bash
git clone [https://github.com/your-username/financial-failover-service.git](https://github.com/your-username/financial-failover-service.git)
cd financial-failover-service
Create a Virtual Environment:

Bash
python3 -m venv venv
source venv/bin/activate
Install Dependencies:

Bash
pip install -r requirements.txt
Configuration:
Copy .env.example to .env and fill in your Twilio credentials and Ngrok URL.

Run the Service:

Bash
python main.py
How it Works (The "P3" Logic)
The system doesn't just "fire and forget." It listens for the completed event from Twilio.

If CallStatus is busy or no-answer, it triggers SMS.

If CallStatus is completed but CallDuration is < 5 seconds, it assumes a hang-up or voicemail and triggers the SMS fallback to ensure the message is delivered.