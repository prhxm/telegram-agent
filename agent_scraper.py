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

# Load .env variables
load_dotenv()
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
openai_key = os.getenv("OPENAI_API_KEY")
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
creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
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

# خواندن پیام‌ها و ذخیره پیام‌های جدید
def run_agent():
    print(f"⏱ Checking for new messages at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")
    client = TelegramClient('session_aihome', api_id, api_hash)

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

                        # Save to Supabase
                        supabase.table(supabase_table).insert({
                            "telegram_date": msg.date.strftime("%Y-%m-%d %H:%M:%S"),
                            "raw_text": data.get("translated_summary", msg.text),
                            "location": data.get("location", "None"),
                            "price": data.get("price", "None"),
                            "property": data.get("property", "None"),
                            "notes": data.get("notes", "None"),
                            "extras": data.get("extras", "None"),
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
