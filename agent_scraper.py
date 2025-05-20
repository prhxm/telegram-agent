import os
import time
import json
from datetime import datetime
from dotenv import load_dotenv
from telethon.sync import TelegramClient
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from supabase import create_client, Client
import json
import base64
import requests

# Load .env variables
load_dotenv()
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
openai_key = os.getenv("OPENAI_API_KEY")

# Decode session only once
session_file = "session_aihome.session"
if not os.path.exists(session_file):
    session_b64 = os.getenv("SESSION_BASE64")
    with open(session_file, "wb") as f:
        f.write(base64.b64decode(session_b64))

with open("groups.txt", "r") as f:
    group_usernames = [line.strip() for line in f if line.strip()]

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase_table = os.getenv("SUPABASE_TABLE")

supabase: Client = create_client(supabase_url, supabase_key)

# OpenAI client
client_gpt = OpenAI(api_key=openai_key)

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds",
         'https://www.googleapis.com/auth/spreadsheets',
         "https://www.googleapis.com/auth/drive.file",
         "https://www.googleapis.com/auth/drive"]

creds_dict = json.loads(os.getenv("GOOGLE_CREDS"))
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gs_client = gspread.authorize(creds)
sheet = gs_client.open("Telegram Home Prices").sheet1

# Extract with GPT
def extract_info_with_gpt(message_text):
    prompt = f"""
You are processing a real estate rental message in Persian or mixed language from a Telegram group.

Your task:
1. Translate the message to English.
2. Summarize it in 1-2 short sentences.
3. Extract the following structured data:
  - Location
  - Price
  - Property structure (e.g., 2-bedroom apartment, studio, shared house, master bedroom, etc.)
  - Notes (like number of bedrooms or urgency)
  - Extras (e.g., pets allowed, furnished, utilities included)

Message:
{message_text}

Return ONLY in this JSON format:
{{
  "translated_summary": "...",
  "location": "...",
  "price": "...",
  "property": "...",
  "notes": "...",
  "extras": "..."
}}
"""
    chat = client_gpt.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return json.loads(chat.choices[0].message.content)

# geocodeAndSave automation
def clean_location(raw):
    if not raw:
        return ''
    return (
        raw.split(',')[0]
        .replace(';', '')
        .replace('Downtown', '')
        .replace('Not specified', '')
        .strip()
    )

def geocode_location(location_text):
    cleaned = clean_location(location_text)
    if not cleaned:
        return None

    base_query = f"{cleaned}, Vancouver, BC, Canada"
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={base_query}&addressdetails=1&limit=1"
    headers = {"User-Agent": "telegram-geocoder-agent"}

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return None

    data = response.json()
    if data and 'lat' in data[0] and 'lon' in data[0]:
        return {
            "lat": float(data[0]["lat"]),
            "lng": float(data[0]["lon"])
        }
    return None


# خواندن پیام‌ها و ذخیره پیام‌های جدید
def run_agent():
    print(f"⏱ Checking for new messages at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")    
    client = TelegramClient(session_file.replace(".session", ""), api_id, api_hash)
    client.connect()
    
    if not client.is_user_authorized():
        print("❌ Session is invalid or expired. Please re-upload SESSION_BASE64.")
        return
    
    
    with client:
        for group_username in group_usernames:
            group_username = group_username.strip()
            print(f"🔍 Scanning group: {group_username}")
            try:
                messages = client.iter_messages(group_username, limit=30)

                for msg in messages:
                    if not msg.text:
                        continue
                    try:
                        print(f"📥 MSG from {group_username}: {msg.text[:50]}...")
                        data = extract_info_with_gpt(msg.text)

                        if not data.get("location") or not data.get("price"):
                            print("⚠️ Skipped: missing location or price.")
                            continue

                        # Check for duplicates
                        existing = supabase.table(supabase_table).select("raw_text").eq("raw_text", msg.text).execute()
                        if existing.data:
                            print("🟡 Skipped: duplicate message")
                            continue
                        
                        #geocode
                        coords = geocode_location(data.get("location"))
                        lat = coords["lat"] if coords else None
                        lng = coords["lng"] if coords else None
                        status = "success" if coords else "failed"

                        # Save to Supabase
                        supabase.table(supabase_table).insert({
                            "telegram_date": msg.date.strftime("%Y-%m-%d %H:%M:%S"),
                            "raw_text": data.get("translated_summary", msg.text),
                            "location": data.get("location", "None"),
                            "price": data.get("price", "None"),
                            "property": data.get("property", "None"),
                            "notes": data.get("notes", "None"),
                            "extras": data.get("extras", "None"),
                            "lat": lat,
                            "lng": lng,
                            "geocode_status": status,
                            "source_group": group_username
                        }).execute()
                        print(f"✅ Stored from {group_username}")

                    except Exception as e:
                        print(f"❌ ERROR inside {group_username}: {e}")
            except Exception as e:
                print(f"❌ Skipped group {group_username}: {e}")
                continue

# Looping every 5 minutes
while True:
    run_agent()
    print("🕔 Sleeping for 5 minutes...\n")
    time.sleep(300)
