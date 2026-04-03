import os
from twilio.rest import Client

def _client():
    return Client(os.environ['TWILIO_ACCOUNT_SID'], os.environ['TWILIO_AUTH_TOKEN'])

def _to_e164(dial_code, local_number):
    """Combine dial code and local number into E.164 format."""
    number = local_number.lstrip('0')
    return f"{dial_code}{number}"

def send_whatsapp(dial_code, local_number, body):
    """Send a WhatsApp message via Twilio.

    Returns (True, sid) on success or (False, error_message) on failure.
    """
    to = f"whatsapp:{_to_e164(dial_code, local_number)}"
    from_ = os.environ.get('TWILIO_WHATSAPP_FROM', 'whatsapp:+14155238886')
    try:
        msg = _client().messages.create(to=to, from_=from_, body=body)
        return True, msg.sid
    except Exception as e:
        return False, str(e)
