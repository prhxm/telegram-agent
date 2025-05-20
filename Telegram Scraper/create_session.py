from telethon.sync import TelegramClient
import base64

# 🚨 مقداردهی API
api_id = 22676800
api_hash = "6781d30fe17eed9ad48614dcf08dc044"

# 🆕 نام session رو انتخاب کن (مثل 'myagent')
session_name = 'myagent'

# 📱 ساخت client و لاگین دستی
with TelegramClient(session_name, api_id, api_hash) as client:
    print("✅ Logged in successfully. Creating session...")

    with open(f'{session_name}.session', 'rb') as f:
        session_data = f.read()

    encoded = base64.b64encode(session_data).decode()

    with open('session_base64.txt', 'w') as out:
        out.write(encoded)

    print("✅ SESSION_BASE64 saved to session_base64.txt")
